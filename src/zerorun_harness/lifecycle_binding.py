# SPDX-License-Identifier: MIT
"""Separately sealed, finite synchronous function acquisition envelope.

The callback supplies a context manager, never an alternate worker target. Its
exit runs after the original function's own cleanup; return/finally and exception
semantics remain Python control flow. This is acquisition plumbing, not policy.
"""
import ast
import copy
import hashlib

from .binding import UnsupportedBinding, safe_path
from .declarative import data_boundary, exact, require, seal, unseal

HOOK = "__zr_lifecycle"


@data_boundary
def generate_lifecycle_binding(binding, declarations):
    """Transform a sealed grammar-1.2 binding with named function envelopes."""
    b = unseal(binding, "zerorun-binding/1")
    require(b["grammar_version"] == "1.2.0", "Lifecycle requires binding grammar 1.2.0")
    require(type(declarations) is dict and 1 <= len(declarations) <= 32,
            "Invalid lifecycle source inventory")
    require(set(declarations) <= set(b["transformed"]), "Missing lifecycle source")
    transformed = copy.deepcopy(b["transformed"])
    rows = []
    for path, specs in sorted(declarations.items()):
        require(safe_path(path) and type(specs) is list and 1 <= len(specs) <= 16,
                "Invalid lifecycle function inventory")
        require(hashlib.sha256(transformed[path].encode()).hexdigest() ==
                b["transformed_sources"][path], "Modified lifecycle input source")
        try:
            tree = ast.parse(transformed[path], filename=path)
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedBinding("Lifecycle input source cannot parse") from exc
        # This spelling cannot resolve to source-owned state. Any appearance is
        # rejected, including reads, aliases, exception targets and match names.
        for n in ast.walk(tree):
            names = []
            if isinstance(n, ast.Name): names.append(n.id)
            if isinstance(n, ast.arg): names.append(n.arg)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(n.name)
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                names.extend(a.asname or a.name.split('.')[0] for a in n.names)
                if any(a.name == '*' for a in n.names):
                    # Supplied literal imports are already proved by the base
                    # binder, but could export this newly reserved hook.
                    from .binding import constant_wildcard_names
                    names.extend(constant_wildcard_names(n, path, b['original']))
            if isinstance(n, (ast.Global, ast.Nonlocal)): names.extend(n.names)
            if isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and n.name:
                names.append(n.name)
            if isinstance(n, ast.MatchMapping) and n.rest: names.append(n.rest)
            if HOOK in names:
                raise UnsupportedBinding("Native source shadows lifecycle hook")
        seen = set()
        # Resolve nested declarations from the inside out; wrapping an outer
        # body must not hide a still-unresolved nested function.
        for spec in sorted(specs,key=lambda s:(-s['function'].count('.'),s['function'])):
            exact(spec, ['function','role'], 'lifecycle declaration')
            require(type(spec['function']) is str and spec['function'] not in seen
                    and spec['role'] in ('parent','worker'), "Invalid lifecycle target")
            seen.add(spec['function'])
            scope = tree
            for part in spec['function'].split('.'):
                candidates = [n for n in scope.body if
                              isinstance(n, ast.FunctionDef) and n.name == part]
                if not part.isidentifier() or len(candidates) != 1:
                    raise UnsupportedBinding('Ambiguous/missing synchronous lifecycle function')
                scope = candidates[0]
            if scope.decorator_list or any(isinstance(n,(ast.Yield,ast.YieldFrom,ast.AsyncFunctionDef))
                                           for n in ast.walk(scope)):
                raise UnsupportedBinding('Unqualified lifecycle decorator/generator/async scope')
            original_body = scope.body
            prefix = []
            if (original_body and isinstance(original_body[0],ast.Expr)
                    and isinstance(original_body[0].value,ast.Constant)
                    and type(original_body[0].value.value) is str):
                prefix, original_body = original_body[:1], original_body[1:]
            call = ast.Call(func=ast.Name(id=HOOK,ctx=ast.Load()), args=[
                ast.Constant(spec['role']),ast.Constant(spec['function']),
                ast.Call(func=ast.Name(id='locals',ctx=ast.Load()),args=[],keywords=[])],
                keywords=[])
            envelope = ast.With(items=[ast.withitem(context_expr=call,optional_vars=None)],
                                body=original_body or [ast.Pass()],type_comment=None)
            ast.copy_location(envelope,scope)
            scope.body = prefix + [envelope]
            rows.append(dict(path=path,function=spec['function'],role=spec['role'],
                             line=scope.lineno))
        tree = ast.fix_missing_locations(tree)
        try:
            compile(tree,path,'exec')
        except (SyntaxError, RecursionError) as exc:
            raise UnsupportedBinding("Lifecycle transformed source cannot compile") from exc
        transformed[path] = ast.unparse(tree)+'\n'
    return seal(dict(schema='zerorun-lifecycle-binding/1',grammar_version='1.2.0',
                     binding_sha256=binding['sha256'],declarations=copy.deepcopy(declarations),
                     input_sources=copy.deepcopy(b['transformed_sources']),sites=rows,
                     transformed=transformed,transformed_sources={
                         p:hashlib.sha256(s.encode()).hexdigest() for p,s in transformed.items()}))


def validate_lifecycle_binding(binding, envelope):
    value=unseal(envelope,'zerorun-lifecycle-binding/1')
    require(generate_lifecycle_binding(binding,value.get('declarations'))==envelope,
            'Lifecycle envelope must regenerate from its sealed base binding')
    return value
