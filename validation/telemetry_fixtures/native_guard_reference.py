"""Native guard baseline, no ZeroRun, observer, mapper or production checker."""
import hashlib
import importlib
import json
from pathlib import Path
import sys

source=Path(sys.argv[1]);expected=sys.argv[2]
assert hashlib.sha256((source/'evalplus/eval/utils.py').read_bytes()).hexdigest()==expected
sys.path.insert(0,str(source))
native=importlib.import_module('evalplus.eval.utils')
native.reliability_guard()
print(json.dumps({'native_value':17,'native_marker':'unchanged'}))
