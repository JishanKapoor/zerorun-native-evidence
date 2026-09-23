# SPDX-License-Identifier: MIT
"""Bounded structural source binding; never infer native semantic qualification."""

import ast
import copy
import hashlib
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
from .projection import RETURN_LOCAL, project

GRAMMAR_VERSION = "1.1.0"
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
    require(grammar_version in {"1.0.0", "1.1.0"}, "Unsupported binding grammar")
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
        {s["path"] for s in p["sites"].values()} <= set(sources),
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
        # The inserted callback and locals() must not resolve to native data.
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
            n.arg for n in ast.walk(tree) if isinstance(n, ast.arg)
        }
        names |= {
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        }
        if grammar_version == "1.1.0":
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
            if bound_names & {HOOK, RETURN_LOCAL, "locals"}:
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
        for site, spec in p["sites"].items():
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
                functions = [
                    n
                    for n in scope.body
                    if isinstance(n, ast.FunctionDef) and n.name == part
                ]
                if not part.isidentifier() or len(functions) != 1:
                    raise UnsupportedBinding(
                        "Missing/ambiguous lexical native function"
                    )
                scope = functions[0]
            function = scope
            # Nested functions, async, generators and context-sensitive local
            # control scopes require a different separately qualified grammar.
            if any(
                isinstance(n, (ast.AsyncFunctionDef, ast.Yield, ast.YieldFrom))
                for n in ast.walk(function)
            ):
                raise UnsupportedBinding("Unqualified generator/async scope")
            if grammar_version == "1.0.0" and any(
                isinstance(n, ast.Lambda) for n in ast.walk(function)
            ):
                raise UnsupportedBinding("Unqualified generator/async scope")
            nodes = []

            def walk(node):
                if node is not function and isinstance(
                    node, (ast.FunctionDef, ast.ClassDef)
                ):
                    return
                if isinstance(node, ast.stmt) and structure(node) == structure(anchor):
                    nodes.append(node)
                for child in ast.iter_child_nodes(node):
                    walk(child)

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
                if any(pos == existing[1] for existing in injections.get(id(node), [])):
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

        class Instrument(ast.NodeTransformer):
            def visit(self, node):
                original_id = id(node)
                node = super().visit(node)
                if original_id not in injections:
                    return node
                before, after, returned = [], [], []
                return_capture = False
                for site, pos in injections[original_id]:
                    hook = ast.Expr(
                        value=ast.Call(
                            func=ast.Name(id=HOOK, ctx=ast.Load()),
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
                        targets=[ast.Name(id=RETURN_LOCAL, ctx=ast.Store())],
                        value=node.value
                        if node.value is not None
                        else ast.Constant(None),
                    )
                    ast.copy_location(assigned, node)
                    node.value = ast.Name(id=RETURN_LOCAL, ctx=ast.Load())
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
        b.get("grammar_version") in {"1.0.0", GRAMMAR_VERSION}
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


def recorder(profile, binding, emitter, producer, *, context=None):
    """Construct pre-guard projection callback; emission never supplies policy.

    Native glue must install this callback before executing transformed code.
    Missing/unrepresentable primitive fields count as telemetry rejection. Native
    exceptions from the emitter, including timeout/termination, still propagate.
    """
    from ._telemetry_protocol import PrimitiveError, primitives

    validate_profile(profile)
    b = validate_binding(profile, binding)
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
    require(type(producer) is int and producer > 0, "Invalid native producer")
    sequence = 0

    def observe(site, local_state):
        nonlocal sequence
        sequence += 1
        spec = profile["sites"][site]
        try:
            values = {
                k: project(value, local_state, identity_context)
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
            binding_sha256=binding["sha256"],
        )
        return emitter.emit(event)

    return observe
