# SPDX-License-Identifier: MIT
"""Check wheel licensing/RECORD integrity and optional cross-platform equivalence."""
import base64
import csv
import email.parser
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path


def check(path):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        assert len(names) == len(set(names)), 'Duplicate wheel member'
        metadata_name = next(n for n in names if n.endswith('.dist-info/METADATA'))
        prefix = metadata_name.removesuffix('METADATA')
        metadata = email.parser.BytesParser().parsebytes(z.read(metadata_name))
        expected = {'LICENSE.txt', 'Licence.txt', 'src/zerorun_harness/_vendor/LICENSE.txt',
                    'src/zerorun_harness/_vendor/NOTICE.txt'}
        assert metadata['License-Expression'] == 'MIT AND Apache-2.0', 'Missing precise SPDX expression'
        assert set(metadata.get_all('License-File', [])) == expected, 'Incomplete license inventory'
        assert metadata['Name'] == 'zerorun-harness' and metadata['Version'] == '0.5.0'
        for name in expected:
            assert prefix + 'licenses/' + name in names, 'Missing declared license: ' + name
        assert z.read(prefix + 'licenses/LICENSE.txt') == z.read(prefix + 'licenses/Licence.txt')
        rows = list(csv.reader(io.StringIO(z.read(prefix + 'RECORD').decode())))
        assert {r[0] for r in rows} == set(names) and len(rows) == len(names)
        for name, fingerprint, length in rows:
            if name == prefix + 'RECORD':
                assert fingerprint == length == ''
                continue
            data = z.read(name)
            expected_hash = 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            assert fingerprint == expected_hash and length == str(len(data)), 'RECORD mismatch: ' + name
        return {n: z.read(n) for n in names}


def equivalent(left, right):
    a, b = check(left), check(right)
    assert set(a) == set(b), 'Different wheel members'
    normalized = []
    for name in a:
        if name.endswith('.dist-info/RECORD'):
            continue  # Each RECORD was verified against its own exact member bytes above.
        if a[name] != b[name]:
            assert '.dist-info/' in name and '/licenses/' not in name
            assert a[name].replace(b'\r\n', b'\n') == b[name].replace(b'\r\n', b'\n'), name
            normalized.append(name)
    return dict(passed=True, same_member_inventory=True, runtime_and_license_bytes_equal=True,
                generated_metadata_newline_differences=normalized, both_record_hashes_verified=True)


if __name__ == '__main__':
    args = list(map(Path, sys.argv[1:]))
    if len(args) == 2:
        result = equivalent(*args)
    elif len(args) == 1:
        path = next(args[0].glob('*.whl')) if args[0].is_dir() else args[0]
        result = dict(passed=True, wheel=path.name, verified_members=len(check(path)))
    else:
        raise SystemExit('Usage: package_checks.py WHEEL_OR_DIST_DIRECTORY [OTHER_WHEEL]')
    print(json.dumps(result, indent=2))
