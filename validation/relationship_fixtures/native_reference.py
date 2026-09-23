"""Observer-free native reference route: ordinary raw-field extraction only."""
import hashlib
import json
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_bytes()
assert hashlib.sha256(source).hexdigest() == sys.argv[2]
namespace = {}
exec(compile(source, sys.argv[1], 'exec'), namespace)
result = namespace['run'](sys.argv[3])
Path(sys.argv[4]).write_text(json.dumps(result))
