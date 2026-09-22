# SPDX-License-Identifier: MIT
"""Reconstruct frozen acquisition inputs; never import or execute candidates."""
import argparse
import hashlib
import json
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent


def checked_bytes(path, identity):
    data = path.read_bytes()
    if len(data) != identity['bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
        raise ValueError('Input identity mismatch: ' + str(path))
    return data


def asset(cache, identity, download):
    target = cache / identity['sha256']
    if not target.exists():
        if not download:
            raise FileNotFoundError('Missing content-addressed cache asset: ' + str(target))
        url = identity.get('source', identity.get('url'))
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(identity['bytes'] + 1)
        if len(data) != identity['bytes'] or hashlib.sha256(data).hexdigest() != identity['sha256']:
            raise ValueError('Downloaded asset differs from frozen identity: ' + url)
        with target.open('xb') as f:
            f.write(data)
    return checked_bytes(target, identity)


def save(root, relative, data):
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or '\\' in relative or ':' in relative:
        raise ValueError('Invalid relative input path')
    target = root.joinpath(*rel.parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError('Input path escapes output directory')
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as f:
        f.write(data)


def prepare(cache, output, download=False):
    manifest = json.loads((ROOT / 'source-manifest.json').read_text(encoding='utf-8'))
    cache.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=False)
    archive = manifest['humaneval-gpt-4-1106-preview-v010.zip']
    asset(cache, archive, download)
    cohort = output / 'cohort'
    study = output / 'study'
    with zipfile.ZipFile(cache / archive['sha256']) as z:
        for row in manifest['evalplus_cohort']['records']:
            data = z.read(row['member'])
            if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                raise ValueError('Candidate member identity mismatch: ' + row['task_id'])
            save(cohort, row['path'], data)
    save(cohort, 'data/HumanEvalPlus-v019.jsonl.gz', asset(cache, manifest['HumanEvalPlus-v019.jsonl.gz'], download))
    for name in ['evalplus', 'swe']:
        save(cohort, 'protocol/' + name + '-cohort.json', json.dumps(manifest[name + '_cohort'], indent=2).encode())
    for row in manifest['swe_logs']['records']:
        save(study, row['path'], asset(cache, row, download))
    save(study, 'protocol/log-acquisition.json', json.dumps(manifest['swe_logs'], indent=2).encode())
    inventory = [dict(path=p.relative_to(output).as_posix(), bytes=p.stat().st_size,
                      sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                 for p in sorted(output.rglob('*')) if p.is_file()]
    return dict(passed=True, candidate_programs=164, saved_logs=10, files=inventory,
                candidate_calls=0, canonical_calls=0,
                note='Inputs reconstructed from immutable identities; new native execution is separate.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--download', action='store_true', help='Fetch absent frozen assets over HTTPS')
    args = parser.parse_args()
    print(json.dumps(prepare(args.cache, args.output, args.download), indent=2))
