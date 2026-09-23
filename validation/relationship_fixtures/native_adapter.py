"""A4 adapter for exposed, source-pinned primitive native API relationships."""
def run(emitter, argument):
    import json
    import os
    from pathlib import Path
    from zerorun_harness.binding import recorder, validate_binding
    root = Path('/fixtures/native') / argument['family']
    profile = json.loads((root / 'profile.json').read_text())
    binding = json.loads((root / 'binding.json').read_text())
    validate_binding(profile, binding)
    callback = recorder(profile, binding, emitter, os.getpid())
    namespace = {'__zr_observe': callback}
    exec(compile(binding['transformed']['native_api.py'], 'native_api.py', 'exec'), namespace)
    return namespace['run'](argument['mode'])
