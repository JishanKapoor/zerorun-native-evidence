"""Frozen, exposed development controls for the actual EvalPlus worker.

These candidates are authored controls, not newly selected benchmark cases.
Neither expected relationships nor checker results enter native candidates.
"""

REVISIONS = {
    "before": "c05b20b24ab6783878d9ffa1ae5496e83da0e65b",
    "after": "6eb1e199c2e370518e7bf3e8eee6322c2b23c89c",
}
NATIVE_PATH = "evalplus/eval/__init__.py"
CONTROLS = [
    dict(id="exact-pass", code="def check(x): return x", inputs=[[1], [2]], expected=[1, 2], entry="check", atol=0, fast=False),
    dict(id="rejected-continuation", code="def check(x): return x", inputs=[[1], [2]], expected=[0, 0], entry="check", atol=0, fast=False),
    dict(id="fast-rejected-prefix", code="def check(x): return x", inputs=[[1], [2]], expected=[0, 0], entry="check", atol=0, fast=True),
    dict(id="mixed-dispositions", code="def check(x): return x", inputs=[[1], [2]], expected=[1, 0], entry="check", atol=0, fast=False),
    dict(id="tolerant-acceptance", code="def check(x): return x", inputs=[[1.0]], expected=[1.0000001], entry="check", atol=0.000001, fast=False),
    dict(id="type-rejection", code="def check(x): return 'bad'", inputs=[[1.0]], expected=[1.0], entry="check", atol=0.000001, fast=False),
    dict(id="invocation-exception", code="def check(x): raise ValueError('authored native exception')", inputs=[[1], [2]], expected=[1, 2], entry="check", atol=0, fast=False),
    dict(id="caught-native-timeout", code="def check(x):\n    while True: pass", inputs=[[1]], expected=[1], entry="check", atol=0, fast=False),
    dict(id="polynomial-accepted-continue", code="def find_zero(xs): return 1.0", inputs=[[[-1.0, 1.0]]], expected=[1.0], entry="find_zero", atol=0.000001, fast=False),
    dict(id="polynomial-rejected", code="def find_zero(xs): return 2.0", inputs=[[[-1.0, 1.0]]], expected=[1.0], entry="find_zero", atol=0.000001, fast=False),
    dict(id="initialization-exception", code="raise RuntimeError('authored initialization exception')", inputs=[[1]], expected=[1], entry="check", atol=0, fast=False),
]


def identity(obligation, case):
    return dict(run="exposed-native-worker", candidate=case["id"], obligation=obligation, phase="base", attempt=1)


def native_kwargs(case):
    return dict(dataset="humaneval", code=case["code"], inputs=case["inputs"], entry_point=case["entry"], expected=case["expected"], atol=case["atol"], ref_time=[0.001] * len(case["inputs"]), fast_check=case["fast"], min_time_limit=0.08, gt_time_limit_factor=4)
