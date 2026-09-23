# SPDX-License-Identifier: MIT
"""Bounded structural source binding; never infer native semantic qualification."""

import ast
import copy
import hashlib
import itertools
from pathlib import PurePosixPath

from .api import InvalidEvidence, digest
from .declarative import (
    data_boundary,
    exact,
    require,
    seal,
    unseal,
    typed,
    validate_profile,
)
from .projection import ACTIVATION_LOCAL, RETURN_LOCAL, project

GRAMMAR_VERSION = "1.2.0"
SUPPORTED_GRAMMARS = {"1.0.0", "1.1.0", GRAMMAR_VERSION, "1.3.0", "1.4.0"}
RECORD_GRAMMARS = {"1.3.0", "1.4.0"}
HOOK = "__zr_observe"


class UnsupportedBinding(InvalidEvidence):
    pass


def safe_path(path):
    return (
        type(path) is str
        and path.endswith(".py")
        and "\\" not in path
        and ":" not in path
        and not PurePosixPath(path).is_absolute()
        and all(p not in ("", ".", "..") for p in path.split("/"))
    )


def structure(node):
    return ast.dump(node, include_attributes=False)


def compound_header(node):
    """Canonical control header: retained tests/targets, never execute expressions."""
    if not isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
        raise UnsupportedBinding("Unsupported native ancestor header")
    node = copy.deepcopy(node)
    for field in ("body", "orelse", "finalbody"):
        if hasattr(node, field):
            setattr(node, field, [])
    if isinstance(node, ast.Try):
        for handler in node.handlers:
            handler.body = []
    return structure(node)


def ancestor_constraints(spec):
    result = []
    for ancestor in spec.get("within", []):
        try:
            header = ast.parse(ancestor["header"]).body
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedBinding("Invalid native ancestor header") from exc
        if len(header) != 1:
            raise UnsupportedBinding("Ancestor requires one compound header")
        node = header[0]
        branch = ancestor["branch"]
        valid = {"body"}
        if isinstance(node, (ast.If, ast.For, ast.While, ast.Try)):
            valid.add("orelse")
        if isinstance(node, ast.Try):
            valid |= {"finalbody"} | {"handler:" + str(i) for i in range(len(node.handlers))}
        if branch not in valid:
            raise UnsupportedBinding("Ancestor branch does not belong to header")
        result.append((compound_header(node), branch))
    return result


def ancestors_match(wanted, actual):
    """Ordered outer-to-inner subsequence of statically witnessed ancestors."""
    cursor = 0
    for item in actual:
        if cursor < len(wanted) and item == wanted[cursor]:
            cursor += 1
    return cursor == len(wanted)


def constant_wildcard_names(node, path, sources):
    """Resolve only a supplied original module with literal constant exports."""
    parts = (node.module or "").split(".") if node.module else []
    if node.level:
        package = path.split("/")[:-1]
        if node.level > len(package):
            raise UnsupportedBinding(
                "Relative wildcard import exceeds source inventory"
            )
        parts = package[: len(package) - node.level + 1] + parts
    base = "/".join(parts)
    matches = [
        name for name in [base + ".py", base + "/__init__.py"] if name in sources
    ]
    if len(matches) != 1:
        raise UnsupportedBinding(
            "Wildcard import requires one original constant source module"
        )
    try:
        tree = ast.parse(sources[matches[0]])
    except SyntaxError as exc:
        raise UnsupportedBinding("Wildcard constant source syntax unsupported") from exc
    constants = {}
    for statement in tree.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and type(statement.value.value) is str
        ):
            continue
        if not isinstance(statement, ast.Assign) or not all(
            isinstance(t, ast.Name) for t in statement.targets
        ):
            raise UnsupportedBinding(
                "Wildcard namespace permits literal constant assignments only"
            )
        try:
            value = ast.literal_eval(statement.value)
        except (ValueError, TypeError, SyntaxError, RecursionError) as exc:
            raise UnsupportedBinding(
                "Wildcard namespace has executable initialization"
            ) from exc
        for target in statement.targets:
            constants[target.id] = value
    exported = constants.get(
        "__all__", [name for name in constants if not name.startswith("_")]
    )
    if type(exported) not in (list, tuple) or not all(
        type(name) is str and name in constants for name in exported
    ):
        raise UnsupportedBinding(
            "Wildcard constant exports must have a literal complete inventory"
        )
    return set(exported)


@data_boundary
def generate_binding(profile, sources, *, grammar_version=GRAMMAR_VERSION):
    """Generate immutable source-specific sites from frozen exact AST anchors.

    Anchors are source statements, not executable predicates. A matching statement
    is never reevaluated. Support is finite and fail-closed on ambiguity/control
    syntax; this is not an arbitrary Python or adversarial-source instrumenter.
    """
    p = validate_profile(profile)
    require(grammar_version in SUPPORTED_GRAMMARS, "Unsupported binding grammar")
    if grammar_version not in RECORD_GRAMMARS:
        require(all('activation' not in value for site in p['sites'].values()
                    for value in site['projection'].values()),
                'Old grammar cannot acquire dynamic activation identity')
        require(all("ordinal" not in site.get("batch",{}) for site in p["sites"].values()),
                "Old grammar cannot separate acquisition ordinal from native identity")
        require(all("item" not in site["projection"][field]
                    for site in p["sites"].values() for field in p["identity"]),
                "Old grammar cannot acquire stored batch item identity")
        require("record_types" not in p and all(
            v.get("encoding") != "number_json" and not any("stored" in step for step in v.get("path",[]))
            for s in p["sites"].values() for v in s["projection"].values()),
            "Old grammar cannot acquire stored record/number-token projections")
    if grammar_version in {"1.0.0", "1.1.0"}:
        require(all(not (set(r) & {"inventory_policy","guard"}) for r in p["rules"]),
                "Old grammar cannot acquire completed native batch policy")
        require(all(not (set(s) & {"within", "producer_role", "batch"}) for s in p["sites"].values()),
                "Old grammar cannot acquire native ancestor/role selection")
        require(
            all(
                not (set(v) & {"size", "contains"})
                and not (set(v) & {"item", "ordinal"})
                and v.get("encoding") != "sorted_json"
                for s in p["sites"].values()
                for v in s["projection"].values()
            ),
            "Old grammar cannot acquire native collection projections",
        )
    if grammar_version == "1.0.0":
        require(
            all(
                s["position"] in {"after", "try_success", "handler_entry"}
                and "." not in s["function"]
                and all(
                    set(v) in ({"local"}, {"literal"}) for v in s["projection"].values()
                )
                for s in p["sites"].values()
            ),
            "Old grammar cannot acquire new projection/binding features",
        )
    require(
        type(sources) is dict and 1 <= len(sources) <= 32, "Invalid source inventory"
    )
    require(
        ({s["path"] for s in p["sites"].values()} |
         {r["path"] for r in p.get("record_types",{}).values()}) <= set(sources),
        "Binding source missing",
    )
    require(
        all(
            safe_path(k) and type(v) is str and len(v.encode("utf-8")) <= 1024 * 1024
            for k, v in sources.items()
        ),
        "Invalid source path or source size",
    )
    originals, transformed, rows = {}, {}, []
    for path, source in sorted(sources.items()):
        originals[path] = hashlib.sha256(source.encode("utf-8")).hexdigest()
        try:
            tree = ast.parse(source, filename=path)
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedBinding("Native source syntax unsupported") from exc
        for declaration in p.get("record_types",{}).values():
            if declaration["path"] != path:continue
            classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==declaration["name"]]
            if len(classes)!=1:
                raise UnsupportedBinding("Missing/ambiguous native record definition")
            annotated={n.target.id for n in classes[0].body if isinstance(n,ast.AnnAssign)
                       and isinstance(n.target,ast.Name)}
            if grammar_version == '1.4.0':
                # Only explicitly named, same-source bases supply additional
                # declarations. Runtime acquisition still validates exact MRO
                # and stored instance fields; no imported base is guessed.
                def inherited_fields(cls, visiting):
                    if id(cls) in visiting:
                        raise UnsupportedBinding('Cyclic native record source inheritance')
                    fields={n.target.id for n in cls.body if isinstance(n,ast.AnnAssign)
                            and isinstance(n.target,ast.Name)}
                    constructors=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__']
                    if len(constructors)>1:
                        raise UnsupportedBinding('Ambiguous native record initializer')
                    if constructors and not constructors[0].decorator_list:
                        constructor=constructors[0]
                        arguments=constructor.args.posonlyargs+constructor.args.args
                        if arguments:
                            instance=arguments[0].arg
                            def stored_annotations(node):
                                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):return
                                if (isinstance(node,ast.AnnAssign) and isinstance(node.target,ast.Attribute)
                                        and isinstance(node.target.value,ast.Name) and node.target.value.id==instance):
                                    fields.add(node.target.attr)
                                for child in ast.iter_child_nodes(node):stored_annotations(child)
                            for statement in constructor.body:stored_annotations(statement)
                    for base in cls.bases:
                        if not isinstance(base,ast.Name):continue
                        matches=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==base.id]
                        if len(matches)>1:
                            raise UnsupportedBinding('Ambiguous native record source base')
                        if matches:
                            declared_base=matches[0]
                            if declared_base.decorator_list:
                                raise UnsupportedBinding('Decorated native record source base')
                            def rebinds(node):
                                if node is declared_base:return False
                                if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                                    # Definition bodies have their own lexical
                                    # names; definition-time expressions do not.
                                    if node.name==base.id:return True
                                    expressions=list(node.decorator_list)
                                    if isinstance(node,ast.ClassDef):
                                        expressions+=node.bases+[k.value for k in node.keywords]
                                    else:
                                        expressions+=node.args.defaults+[v for v in node.args.kw_defaults if v is not None]
                                        expressions+=[arg.annotation for arg in node.args.posonlyargs+node.args.args+node.args.kwonlyargs if arg.annotation is not None]
                                        expressions+=[arg.annotation for arg in (node.args.vararg,node.args.kwarg) if arg is not None and arg.annotation is not None]
                                        if node.returns is not None:expressions.append(node.returns)
                                    return any(rebinds(value) for value in expressions)
                                if isinstance(node,ast.Lambda):
                                    return any(rebinds(value) for value in node.args.defaults+[v for v in node.args.kw_defaults if v is not None])
                                if isinstance(node,ast.Name) and isinstance(node.ctx,(ast.Store,ast.Del)) and node.id==base.id:return True
                                if isinstance(node,(ast.Import,ast.ImportFrom)):
                                    if any(alias.name=='*' or (alias.asname or alias.name.split('.')[0])==base.id for alias in node.names):return True
                                if isinstance(node,ast.ExceptHandler) and node.name==base.id:return True
                                if isinstance(node,(ast.MatchAs,ast.MatchStar)) and node.name==base.id:return True
                                if isinstance(node,ast.MatchMapping) and node.rest==base.id:return True
                                return any(rebinds(child) for child in ast.iter_child_nodes(node))
                            if any(rebinds(statement) for statement in tree.body):
                                raise UnsupportedBinding('Native record source base identity is rebound')
                            fields.update(inherited_fields(declared_base,visiting|{id(cls)}))
                    return fields
                annotated=inherited_fields(classes[0],set())
            if not set(declaration["fields"])<=annotated:
                raise UnsupportedBinding("Native record fields lack original annotated declarations")
        # The inserted callback and locals() must not resolve to native data.
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)
        }
        names |= {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        if grammar_version in RECORD_GRAMMARS and ACTIVATION_LOCAL in names:
            raise UnsupportedBinding('Native source shadows activation identity')
        if grammar_version == '1.4.0' and names & {HOOK+'__',RETURN_LOCAL+'__',ACTIVATION_LOCAL+'__'}:
            raise UnsupportedBinding('Native source shadows unmangled method observation plumbing')
        if grammar_version != "1.0.0":
            bound_names = {
                n.id
                for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
            }
            bound_names |= {n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)}
            bound_names |= {
                n.name
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            }
            for n in ast.walk(tree):
                if isinstance(n, (ast.Import, ast.ImportFrom)):
                    if any(a.name == "*" for a in n.names):
                        if not isinstance(n, ast.ImportFrom):
                            raise UnsupportedBinding("Unqualified wildcard namespace")
                        bound_names.update(constant_wildcard_names(n, path, sources))
                    else:
                        bound_names.update(
                            a.asname or a.name.split(".")[0] for a in n.names
                        )
                elif isinstance(n, (ast.Global, ast.Nonlocal)):
                    bound_names.update(n.names)
                elif (
                    isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
                    and n.name
                ):
                    bound_names.add(n.name)
                elif isinstance(n, ast.MatchMapping) and n.rest:
                    bound_names.add(n.rest)
            if bound_names & ({HOOK, RETURN_LOCAL, "locals"} |
                               ({ACTIVATION_LOCAL} if grammar_version in RECORD_GRAMMARS else set()) |
                               ({HOOK+'__',RETURN_LOCAL+'__',ACTIVATION_LOCAL+'__'} if grammar_version=='1.4.0' else set())):
                raise UnsupportedBinding("Native source shadows observation plumbing")
        if (
            HOOK in names
            or any(
                isinstance(n, ast.Name)
                and n.id == "locals"
                and isinstance(n.ctx, ast.Store)
                for n in ast.walk(tree)
            )
            or any(isinstance(n, ast.arg) and n.arg == "locals" for n in ast.walk(tree))
        ):
            raise UnsupportedBinding("Native source shadows observation plumbing")
        if any(
            isinstance(n, (ast.Global, ast.Nonlocal))
            and ("locals" in n.names or HOOK in n.names)
            for n in ast.walk(tree)
        ):
            raise UnsupportedBinding("Native scope aliases observation plumbing")
        for n in ast.walk(tree):
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                if any(
                    (a.asname or a.name.split(".")[0]) in ("locals", HOOK)
                    for a in n.names
                ):
                    raise UnsupportedBinding(
                        "Native import shadows observation plumbing"
                    )
        injections = {}
        activations = {}
        introspection_aliases = {name:name for name in ('locals','vars','dir','eval','exec')}
        if grammar_version in RECORD_GRAMMARS:
            for node in ast.walk(tree):
                if isinstance(node,ast.ImportFrom) and node.module == 'builtins':
                    for alias in node.names:
                        if alias.name in introspection_aliases:
                            introspection_aliases[alias.asname or alias.name] = alias.name
            # Finite direct alias closure, not arbitrary dynamic name analysis.
            alias_edges={}
            for node in ast.walk(tree):
                if not isinstance(node,ast.Assign):continue
                origin=(node.value.id if isinstance(node.value,ast.Name)
                        else node.value.attr if isinstance(node.value,ast.Attribute)
                             and node.value.attr in {'locals','vars','eval','exec'} else None)
                if origin:
                    alias_edges.setdefault(origin,[]).extend(target.id for target in node.targets
                                                              if isinstance(target,ast.Name))
            pending=list(introspection_aliases)
            for origin in pending:
                for target in alias_edges.get(origin,[]):
                    if target not in introspection_aliases:
                        introspection_aliases[target]=introspection_aliases[origin]
                        pending.append(target)
        declared_sites = (sorted(p["sites"].items()) if grammar_version in {"1.2.0","1.3.0","1.4.0"}
                          else p["sites"].items())
        for site, spec in declared_sites:
            if spec["path"] != path:
                continue
            try:
                anchor = ast.parse(spec["anchor"]).body
            except (SyntaxError, RecursionError) as exc:
                raise UnsupportedBinding("Invalid structural anchor") from exc
            if len(anchor) != 1:
                raise UnsupportedBinding(
                    "Exactly one native statement anchor is required"
                )
            anchor = anchor[0]
            scope = tree
            for part in spec["function"].split("."):
                if grammar_version in RECORD_GRAMMARS:
                    candidates=[]
                    def lexical(node):
                        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                            candidates.append(node)
                            return
                        if isinstance(node,ast.ClassDef):
                            if grammar_version == '1.4.0':candidates.append(node)
                            return
                        for child in ast.iter_child_nodes(node):lexical(child)
                    for node in scope.body:lexical(node)
                    functions=[n for n in candidates if n.name==part]
                else:
                    functions = [n for n in scope.body
                                 if isinstance(n, ast.FunctionDef) and n.name == part]
                if not part.isidentifier() or len(functions) != 1:
                    raise UnsupportedBinding(
                        "Missing/ambiguous lexical native function"
                    )
                scope = functions[0]
            function = scope
            if not isinstance(function,(ast.FunctionDef,ast.AsyncFunctionDef)):
                raise UnsupportedBinding('Native site must end at a lexical function or method')
            if any('activation' in value for value in spec['projection'].values()):
                activations[id(function)] = path + ':' + spec['function']
            # Nested functions, async, generators and context-sensitive local
            # control scopes require a different separately qualified grammar.
            if grammar_version in RECORD_GRAMMARS:
                local_nodes=[]
                def local_walk(node):
                    if node is not function and isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                        # Definition-time expressions execute in this frame;
                        # the nested function/class body has a separate scope.
                        for decorator in node.decorator_list:local_walk(decorator)
                        if isinstance(node,ast.ClassDef):
                            for base in node.bases:local_walk(base)
                            for keyword in node.keywords:local_walk(keyword.value)
                        else:
                            for default in node.args.defaults + [v for v in node.args.kw_defaults if v is not None]:
                                local_walk(default)
                            for arg in node.args.posonlyargs + node.args.args + node.args.kwonlyargs:
                                if arg.annotation is not None:local_walk(arg.annotation)
                            for arg in (node.args.vararg,node.args.kwarg):
                                if arg is not None and arg.annotation is not None:local_walk(arg.annotation)
                            if node.returns is not None:local_walk(node.returns)
                        return
                    local_nodes.append(node)
                    for child in ast.iter_child_nodes(node):local_walk(child)
                local_walk(function)
                def introspection_name(call):
                    if isinstance(call.func,ast.Name):return introspection_aliases.get(call.func.id)
                    if isinstance(call.func,ast.Attribute):return call.func.attr
                    return None
                if (id(function) in activations or (grammar_version=='1.4.0' and spec['position']=='return_value')) and any(
                        isinstance(node,ast.Call) and isinstance(node.func,(ast.Name,ast.Attribute))
                        and (introspection_name(node) in {'locals','eval','exec'}
                             or (introspection_name(node) in {'vars','dir'}
                                 and not node.args and not node.keywords))
                        for node in local_nodes):
                    raise UnsupportedBinding('Native local introspection can observe reserved activation state or return temporary')
                unsupported = any(isinstance(n,(ast.Yield,ast.YieldFrom)) for n in local_nodes)
                unsupported |= isinstance(function,ast.AsyncFunctionDef) and bool(function.decorator_list)
            else:
                unsupported = any(isinstance(n,(ast.AsyncFunctionDef,ast.Yield,ast.YieldFrom))
                                  for n in ast.walk(function))
            if unsupported:
                raise UnsupportedBinding("Unqualified generator/async scope")
            if grammar_version == "1.0.0" and any(
                isinstance(n, ast.Lambda) for n in ast.walk(function)
            ):
                raise UnsupportedBinding("Unqualified generator/async scope")
            nodes = []

            constraints = ancestor_constraints(spec)

            def walk(node, ancestors=()):
                if node is not function and (isinstance(node, (ast.FunctionDef, ast.ClassDef))
                                            or (grammar_version in RECORD_GRAMMARS and isinstance(node,ast.AsyncFunctionDef))):
                    return
                if (isinstance(node, ast.stmt) and structure(node) == structure(anchor)
                        and ancestors_match(constraints, ancestors)):
                    nodes.append(node)
                if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                    header = compound_header(node)
                    for field, value in ast.iter_fields(node):
                        if field in {"body", "orelse", "finalbody"}:
                            for child in value:
                                walk(child, ancestors + ((header, field),))
                        elif field == "handlers":
                            for i, handler in enumerate(value):
                                for child in handler.body:
                                    walk(child, ancestors + ((header, "handler:" + str(i)),))
                        elif isinstance(value, ast.AST):
                            walk(value, ancestors)
                        elif isinstance(value, list):
                            for child in value:
                                if isinstance(child, ast.AST):
                                    walk(child, ancestors)
                else:
                    for child in ast.iter_child_nodes(node):
                        walk(child, ancestors)

            walk(function)
            if len(nodes) != spec["multiplicity"]:
                raise UnsupportedBinding("Static multiplicity mismatch for " + site)
            for node in nodes:
                pos = spec["position"]
                if (
                    (
                        pos in {"before", "after"}
                        and not isinstance(
                            node,
                            (
                                ast.Assign,
                                ast.AnnAssign,
                                ast.AugAssign,
                                ast.Expr,
                                ast.Assert,
                            ),
                        )
                    )
                    or (pos == "try_success" and not isinstance(node, ast.Try))
                    or (pos == "handler_entry" and not isinstance(node, ast.Try))
                    or (
                        pos in {"before_return", "return_value"}
                        and not isinstance(node, ast.Return)
                    )
                ):
                    raise UnsupportedBinding("Unqualified native control-flow anchor")
                if pos == "handler_entry" and len(node.handlers) != 1:
                    raise UnsupportedBinding(
                        "Handler entry requires one explicit native handler"
                    )
                if grammar_version in {"1.0.0","1.1.0"} and any(
                    pos == existing[1] for existing in injections.get(id(node), [])
                ):
                    raise UnsupportedBinding(
                        "Multiple declarations target the same native statement"
                    )
                injections.setdefault(id(node), []).append((site, pos))
                rows.append(
                    dict(
                        site=site,
                        path=path,
                        function=spec["function"],
                        line=node.lineno,
                        end_line=node.end_lineno,
                        position=pos,
                        kind=spec["kind"],
                        anchor_sha256=hashlib.sha256(
                            structure(node).encode()
                        ).hexdigest(),
                        static_multiplicity=spec["multiplicity"],
                    )
                )

        hook_name=HOOK+'__' if grammar_version=='1.4.0' else HOOK
        return_name=RETURN_LOCAL+'__' if grammar_version=='1.4.0' else RETURN_LOCAL
        activation_name=ACTIVATION_LOCAL+'__' if grammar_version=='1.4.0' else ACTIVATION_LOCAL

        class Instrument(ast.NodeTransformer):
            def visit(self, node):
                original_id = id(node)
                node = super().visit(node)
                if original_id in activations:
                    entry = ast.Assign(targets=[ast.Name(id=activation_name,ctx=ast.Store())],
                        value=ast.Call(func=ast.Attribute(value=ast.Name(id=hook_name,ctx=ast.Load()),
                            attr='enter',ctx=ast.Load()),args=[ast.Constant(activations[original_id])],keywords=[]))
                    ast.copy_location(entry,node)
                    has_docstring = (node.body and isinstance(node.body[0],ast.Expr)
                                     and isinstance(node.body[0].value,ast.Constant)
                                     and isinstance(node.body[0].value.value,str))
                    node.body.insert(1 if has_docstring else 0,entry)
                if original_id not in injections:
                    return node
                before, after, returned = [], [], []
                return_capture = False
                for site, pos in injections[original_id]:
                    hook = ast.Expr(
                        value=ast.Call(
                            func=ast.Name(id=hook_name, ctx=ast.Load()),
                            args=[
                                ast.Constant(site),
                                ast.Call(
                                    func=ast.Name(id="locals", ctx=ast.Load()),
                                    args=[],
                                    keywords=[],
                                ),
                            ],
                            keywords=[],
                        )
                    )
                    ast.copy_location(hook, node)
                    if pos == "after":
                        after.append(hook)
                    elif pos in {"before", "before_return"}:
                        before.append(hook)
                    elif pos == "return_value":
                        return_capture = True
                        returned.append(hook)
                    elif pos == "try_success":
                        # Only successful completion, never a caught exception,
                        # continue or return from the original try body.
                        node.orelse.insert(0, hook)
                    else:
                        node.handlers[0].body.insert(0, hook)
                if return_capture:
                    assigned = ast.Assign(
                        targets=[ast.Name(id=return_name, ctx=ast.Store())],
                        value=node.value
                        if node.value is not None
                        else ast.Constant(None),
                    )
                    ast.copy_location(assigned, node)
                    node.value = ast.Name(id=return_name, ctx=ast.Load())
                    return before + [assigned] + returned + [node]
                return before + [node] + after if before or after else node

        result = ast.fix_missing_locations(Instrument().visit(tree))
        try:
            compile(result, path, "exec")
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedBinding(
                "Native source cannot compile under qualified grammar"
            ) from exc
        transformed[path] = ast.unparse(result) + "\n"
    return seal(
        dict(
            schema="zerorun-binding/1",
            grammar_version=grammar_version,
            policy_sha256=digest(p),
            original_sources=originals,
            original=copy.deepcopy(sources),
            transformed_sources={
                k: hashlib.sha256(v.encode()).hexdigest()
                for k, v in transformed.items()
            },
            sites=rows,
            transformed=transformed,
            runtime={
                "implementation": "cpython",
                "python": "3.11.16",
                "platform": "linux",
                "start_method": "fork",
                "optimize": 0,
            },
        )
    )


@data_boundary
def validate_binding(p, binding):
    b = unseal(binding, "zerorun-binding/1")
    exact(
        b,
        [
            "schema",
            "grammar_version",
            "policy_sha256",
            "original_sources",
            "original",
            "transformed_sources",
            "sites",
            "transformed",
            "runtime",
        ],
        "generated binding",
    )
    require(
        b.get("grammar_version") in SUPPORTED_GRAMMARS
        and b.get("policy_sha256") == digest(p),
        "Binding policy/grammar identity mismatch",
    )
    require(
        set(b.get("original_sources", {}))
        == set(b.get("transformed_sources", {}))
        == set(b.get("transformed", {})),
        "Binding source inventory mismatch",
    )
    require(
        all(
            hashlib.sha256(v.encode()).hexdigest() == b["transformed_sources"][k]
            for k, v in b["transformed"].items()
        ),
        "Transformed source identity mismatch",
    )
    require(
        {row["site"] for row in b.get("sites", [])} == set(p["sites"]),
        "Incomplete generated site inventory",
    )
    for site, spec in p["sites"].items():
        require(
            sum(row["site"] == site for row in b["sites"]) == spec["multiplicity"],
            "Changed static multiplicity",
        )
    require(
        generate_binding(p, b["original"], grammar_version=b["grammar_version"])
        == binding,
        "Binding must be mechanically regenerated from the frozen declarations",
    )
    return b


def recorder(profile, binding, emitter, producer, *, context=None, records=None):
    """Construct pre-guard projection callback; emission never supplies policy.

    Native glue must install this callback before executing transformed code.
    Missing/unrepresentable primitive fields count as telemetry rejection. Native
    exceptions from the emitter, including timeout/termination, still propagate.
    """
    from ._telemetry_protocol import PrimitiveError, primitives

    validate_profile(profile)
    b = validate_binding(profile, binding)
    # A verified callback must not be retargeted by later caller-side edits.
    profile = copy.deepcopy(profile)
    binding_id = binding["sha256"]
    raw_context = {} if context is None else context
    require(
        type(raw_context) is dict, "Identity context must be an exact primitive mapping"
    )
    try:
        primitives(raw_context)
    except PrimitiveError as exc:
        raise InvalidEvidence("Identity context exceeds primitive bounds") from exc
    identity_context = copy.deepcopy(raw_context)
    fields = [
        (key, value["context"])
        for site in profile["sites"].values()
        for key, value in site["projection"].items()
        if "context" in value
    ]
    require(
        type(identity_context) is dict
        and set(identity_context) == {name for _, name in fields},
        "Identity context must match declared metadata fields",
    )
    require(
        all(
            typed(identity_context[name], profile["identity"][key])
            for key, name in fields
        ),
        "Identity context types do not match native inventory",
    )
    primitives(identity_context)
    source_id = digest(b["original_sources"])
    if profile.get("record_types"):
        from .records import RecordRegistry
        require(type(records) is RecordRegistry
                and records.binding_sha256 == binding_id
                and records.policy_sha256 == digest(profile),
                "Declared records require source-matched registered native classes")
    require(type(producer) is int and producer > 0, "Invalid native producer")
    sequence = 0
    batch_sequence = 0
    activation_counter = itertools.count(1)
    activation_functions = {site['path']+':'+site['function'] for site in profile['sites'].values()
                            if any('activation' in value for value in site['projection'].values())}

    def enter(function):
        value = next(activation_counter)
        if type(function) is not str or function not in activation_functions or value > 32768:
            emitter.emit(object())
            return None
        return value

    def emit_one(site, local_state, *, item=None, ordinal=None, batch=None):
        nonlocal sequence
        sequence += 1
        spec = profile["sites"][site]
        try:
            values = {
                k: project(value, local_state, identity_context, item=item, ordinal=ordinal,records=records)
                for k, value in spec["projection"].items()
            }
            primitives(values)
        except (KeyError, PrimitiveError):
            # None cannot masquerade as a valid native event; count a rejected
            # callback through the emitter's exact-primitive rejection route.
            return emitter.emit(object())
        event = dict(
            id=str(producer) + ":" + str(sequence),
            kind=spec["kind"],
            site=site,
            identity={k: values[k] for k in profile["identity"]},
            values={k: values[k] for k in profile["facts"][spec["kind"]]},
            producer=producer,
            seq=sequence,
            source_sha256=source_id,
            binding_sha256=binding_id,
        )
        if spec.get('batch',{}).get('ordinal') == 'acquisition':
            event['acquisition'] = dict(batch=batch,ordinal=ordinal)
        return emitter.emit(event)

    def observe(site, local_state):
        nonlocal batch_sequence
        if b['grammar_version']=='1.4.0':
            # Dunder-terminated plumbing does not undergo class name mangling.
            # Normalize only our reserved temporary keys for the old projector;
            # native locals and their values retain their actual identities.
            local_state=dict(local_state)
            for name in (RETURN_LOCAL,ACTIVATION_LOCAL):
                if name+'__' in local_state:local_state[name]=local_state.pop(name+'__')
        spec=profile["sites"][site]
        if "batch" not in spec:
            return emit_one(site,local_state)
        collection=local_state.get(spec["batch"]["local"])
        if ((type(collection) is not list and type(collection) is not tuple)
                or len(collection)>spec["batch"]["max_items"]):
            return emitter.emit(object())
        # Snapshot only the actual already materialized native sequence. No
        # native slice/expression is repeated; no element is synthesized.
        snapshot=tuple(collection)
        try:
            batch_identity={k:project(spec["projection"][k],local_state,identity_context,records=records)
                            for k in profile["identity"]
                            if not (set(spec["projection"][k]) & {"ordinal","item"})}
            primitives(batch_identity)
            if not all(typed(v,profile["identity"][k]) for k,v in batch_identity.items()):
                raise PrimitiveError("Invalid native batch identity")
        except (KeyError,PrimitiveError):
            return emitter.emit(object())
        batch_sequence+=1
        control=dict(schema="zerorun-native-batch/1",site=site,
                     producer=producer,binding_sha256=binding_id,
                     batch=batch_sequence,size=len(snapshot),identity=batch_identity)
        accepted=emitter.emit(dict(control,stage="begin"))
        for ordinal,item in enumerate(snapshot):
            accepted=emit_one(site,local_state,item=item,ordinal=ordinal,batch=batch_sequence) and accepted
        return emitter.emit(dict(control,stage="end")) and accepted

    observe.enter = enter
    return observe
