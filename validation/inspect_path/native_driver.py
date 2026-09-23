"""Original Inspect imports and authored eval recipe; no framework imports."""
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import importlib.metadata
import json
from pathlib import Path
import sys


def source_inventory(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root / 'inspect_ai').rglob('*.py'))}


def load_native(root, hashes, transformed=None, observe=None):
    root = Path(root).resolve()
    if source_inventory(root) != hashes:
        raise ValueError('Original Inspect source inventory changed')
    if any(n == 'inspect_ai' or n.startswith('inspect_ai.') for n in sys.modules):
        raise ValueError('Native Inspect must be imported in a fresh process')

    class VerifiedLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            relative = Path(self.path).relative_to(root).as_posix()
            source = Path(self.path).read_bytes()
            if hashlib.sha256(source).hexdigest() != hashes[relative]:
                raise ValueError('Native source changed during import')
            return compile((transformed or {}).get(relative, source), self.path, 'exec')

        def exec_module(self, module):
            if observe is not None and Path(self.path).relative_to(root).as_posix() in (transformed or {}):
                module.__dict__['__zr_observe'] = observe
            super().exec_module(module)

    class VerifiedFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != 'inspect_ai' and not fullname.startswith('inspect_ai.'):
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            if spec is None:
                raise ImportError('Unresolved Inspect source module: ' + fullname)
            if spec.origin is None:
                # Original namespace packages contain no initializer to execute.
                # Admit only the native package's exact pinned source subtree.
                locations=list(spec.submodule_search_locations or [])
                if not locations or any(not Path(location).resolve().is_relative_to(root) for location in locations):
                    raise ImportError('Native namespace escapes original source: ' + fullname)
                for location in locations:
                    prefix=Path(location).resolve().relative_to(root).as_posix()+'/'
                    if not any(path.startswith(prefix) for path in hashes):
                        raise ImportError('Native namespace has no pinned Python source: ' + fullname)
                return spec
            relative = Path(spec.origin).resolve().relative_to(root).as_posix()
            if relative not in hashes:
                raise ImportError('Unpinned native module: ' + fullname)
            spec.loader = VerifiedLoader(fullname, spec.origin)
            return spec

    finder = VerifiedFinder()
    sys.path.insert(0, str(root))
    sys.meta_path.insert(0, finder)
    try:
        package = importlib.import_module('inspect_ai')
        metric = importlib.import_module('inspect_ai.scorer._metric')
        importlib.import_module('inspect_ai._eval.task.results')
        importlib.import_module('inspect_ai._eval.task.run')
    except BaseException:
        sys.meta_path.remove(finder)
        raise
    finally:
        sys.path.remove(str(root))
    # The fresh capture process owns this finder through all later native lazy
    # imports. Actual package __path__ values retain the original source root.
    return package, metric


def run_case(native, case, work, journal_path):
    work = Path(work)
    work.mkdir(parents=True, exist_ok=False)
    journal_path = Path(journal_path)

    def journal(event, **values):
        with journal_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(dict(event=event, **values), allow_nan=False) + '\n')

    if case['order'] == []:
        return dict(stable=None, native_calls=0, callback_calls=0,
                    native_version=importlib.metadata.version('inspect_ai'))
    if case['order'] not in [['a', 'b'], ['b', 'a']]:
        raise ValueError('Only the two frozen authored scorer orders are admitted')
    from inspect_ai import Task, eval as native_eval
    from inspect_ai.dataset import Sample
    from inspect_ai.scorer import Score, Scorer, Target, accuracy, frequency, scorer
    from inspect_ai.solver import Generate, TaskState, solver

    @solver
    def no_generation():
        async def solve(state: TaskState, generate: Generate):
            return state
        return solve

    callbacks = []

    def callback(which, state):
        values = dict(scorer=which, sample=state.sample_id, epoch=state.epoch)
        callbacks.append(values)
        journal('authored_scorer_entered', **values)

    @scorer(metrics=[accuracy(), frequency(categories=[0.0, 1.0])])
    def scorer_a() -> Scorer:
        async def score(state: TaskState, target: Target):
            callback('a', state)
            if case.get('empty_scores'):
                return None
            identity = dict(sample_id=state.sample_id, epoch=state.epoch, fixture_scorer='a')
            if state.sample_id == 3:
                return Score.unscored(reason='fixture_a_unscored', metadata=identity)
            return Score(value=0.0 if (state.sample_id, state.epoch) == (1, 2) else 1.0, metadata=identity)
        return score

    @scorer(metrics=[accuracy(), frequency(categories=[0.0, 1.0])])
    def scorer_b() -> Scorer:
        async def score(state: TaskState, target: Target):
            callback('b', state)
            if case.get('empty_scores'):
                return None
            identity = dict(sample_id=state.sample_id, epoch=state.epoch, fixture_scorer='b')
            if (state.sample_id, state.epoch) == (2, 1):
                raise RuntimeError('authored finite scorer error')
            if (state.sample_id, state.epoch) == (1, 2):
                return None
            if (state.sample_id, state.epoch) == (1, 1):
                return Score.unscored(reason='fixture_b_unscored', metadata=identity)
            return Score(value=0.0 if state.sample_id == 2 else 1.0, metadata=identity)
        return score

    scorers = {'a': scorer_a(), 'b': scorer_b()}
    task = Task(dataset=[Sample(id=i, input='fixed authored control', target='unused',
                                metadata={'control_sample': i}) for i in [1, 2, 3]],
                solver=no_generation(), scorer=[scorers[s] for s in case['order']], epochs=2)
    journal('eval_entered')
    try:
        logs = native_eval(task, model='mockllm/model', fail_on_error=False, display='none', score_display=False,
                           log_dir=str(work / 'native-logs'), max_samples=1)
    except BaseException as error:
        journal('eval_raised', type=type(error).__name__, message=str(error))
        raise
    journal('eval_returned', logs=len(logs))
    if len(logs) != 1:
        raise ValueError('One original native eval must return one log')
    log = logs[0]
    native_wire = log.model_dump_json()
    (work / 'native-log.json').write_text(native_wire, encoding='utf-8')
    # The complete native log is retained. The stable comparison prospectively
    # excludes UUIDs, wall times, durations, and operational traceback locations.
    samples = [dict(sample_id=s.id, epoch=s.epoch, input=s.input, target=s.target,
                    metadata=s.metadata, error_message=s.error.message if s.error else None,
                    scores={name: value.model_dump_json() for name, value in (s.scores or {}).items()})
               for s in sorted(log.samples or [], key=lambda s: (str(s.id), s.epoch))]
    stable = dict(status=log.status, samples=samples,
                  results_wire=log.results.model_dump_json() if log.results else None,
                  reductions_wire=[r.model_dump_json() for r in (log.reductions or [])],
                  model_usage={name: usage.model_dump() for name, usage in log.stats.model_usage.items()})
    return dict(stable=stable, native_calls=1, callback_calls=len(callbacks),
                callbacks=callbacks, native_version=importlib.metadata.version('inspect_ai'))
