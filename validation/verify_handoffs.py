# SPDX-License-Identifier: MIT
"""Rebuild all deposited scripts from their exact recipes without native calls."""
import hashlib
import json
from pathlib import Path
import sys

from zerorun_harness import export
import zerorun_harness.api as api

root=Path(sys.argv[1])
index=json.loads((root/'inputs/export-index.json').read_text())
for row in index['rows']:
    bundle=json.loads((root/'inputs'/(row['name']+'.capture.json')).read_text())
    recipe=json.loads((root/'inputs'/(row['name']+'.recipe.json')).read_text())
    script=export(bundle,mode='native-regression',recipe=recipe)
    assert hashlib.sha256(script.encode('utf-8')).hexdigest()==row['script_sha256'], row['name']
    assert (root/row['script']).read_bytes()==script.encode('utf-8'), row['name']
    origin=root/'reference-origins'/(row['reference_origin_sha256']+'.json')
    assert hashlib.sha256(origin.read_bytes()).hexdigest()==row['reference_origin_sha256']
    original=api.audit
    try:
        api.audit=lambda *a: {'records':[], 'counts':{'FALSE_CLASSIFIER_RESULT':12345}}
        assert export(bundle,mode='native-regression',recipe=recipe)==script
    finally:api.audit=original
print(json.dumps(dict(passed=True,regenerated_native_scripts=len(index['rows']),
                      classifier_corruption_invariant=True,reference_origins_verified=True,native_calls=0)))
