"""Independent original-source trace reference; no framework/profile imports.

Score values are opaque numeric JSON tokens. Source statements and the raw
field extraction below are handwritten independently of the mechanical mapper.
The actual eval, reducers, metric functions, and serializers remain original.
"""
import ast
import dis
import json
from pathlib import Path
import shutil
import sys
from types import CodeType

sys.path.insert(0, str(Path(__file__).parent))
if __package__:
    from .native_driver import load_native, run_case
else:
    from native_driver import load_native, run_case

RUN = 'inspect_ai/_eval/task/run.py'
RESULTS = 'inspect_ai/_eval/task/results.py'
ACTIVATED = {'compute_eval_scores_for_views', 'scorer_for_metrics'}
SELECTED = ACTIVATED | {'_task_run_sample_attempt'}
FIELDS = {'scorer_name', 'score_result', 'results', 'scores', 'reduced_scores',
          'reducer_display_nm', 'sample_scores', 'sample_scores_with_values',
          'unscored_samples', 'scored_samples', 'reducer_name', 'base_metric_name', 'group', 'key'}


def trace_run(root, native, case, work, journal_path):
    paths = {str(Path(root) / path): path for path in [RUN, RESULTS]}
    Score, SampleScore = native[1].Score, native[1].SampleScore
    rows, calls, activations, bytecodes = [], {}, {}, {}
    activation = 0

    def snapshot(value):
        if type(value) is Score:
            # Native source supports number-valued fixture scores only here.
            # JSON preserves NaN distinctly and never converts it into zero.
            return dict(native_record='Score', raw=json.dumps(value.value, allow_nan=True, separators=(',', ':')),
                        metadata=snapshot(value.metadata), native_wire=value.model_dump_json())
        if type(value) is SampleScore:
            return dict(native_record='SampleScore', sample_id=value.sample_id,
                        scorer=value.scorer, score=snapshot(value.score))
        if value is None or type(value) in (str, int, bool):
            return value
        if type(value) is float:
            return dict(native_number=json.dumps(value, allow_nan=True))
        if type(value) in (list, tuple):
            return [snapshot(v) for v in value]
        if type(value) is dict and all(type(k) is str for k in value):
            return {k: snapshot(v) for k, v in value.items()}
        raise ValueError('Undeclared reference snapshot type')

    def trace(frame, event, arg):
        nonlocal activation
        if frame.f_code.co_filename not in paths or frame.f_code.co_name not in SELECTED:
            return trace
        if frame not in calls:
            calls[frame] = len(calls) + 1
        if event == 'call' and frame.f_code.co_name in ACTIVATED:
            if frame in activations:
                raise ValueError('Selected synchronous function resumed unexpectedly')
            activation += 1
            activations[frame] = activation
        if event not in ('call', 'line', 'return', 'exception'):
            return trace
        state = {}
        for name in FIELDS & frame.f_locals.keys():
            try:
                state[name] = snapshot(frame.f_locals[name])
            except ValueError:
                pass
        row = dict(call=calls[frame], activation=activations.get(frame, 0),
                   path=paths[frame.f_code.co_filename], function=frame.f_code.co_name,
                   event=event, line=frame.f_lineno, locals=state)
        if frame.f_code not in bytecodes:
            bytecodes[frame.f_code]={i.offset:i for i in dis.get_instructions(frame.f_code)}
        instruction=bytecodes[frame.f_code].get(frame.f_lasti)
        row['offset']=frame.f_lasti
        row['opcode']=instruction.opname if instruction else None
        row['positions']=list(instruction.positions) if instruction else None
        if event == 'exception':
            row['exception'] = arg[0].__name__
        rows.append(row)
        return trace

    if sys.gettrace() is not None:
        raise ValueError('A preexisting tracer would invalidate this reference')
    sys.settrace(trace)
    try:
        result = run_case(native, case, work, journal_path)
    finally:
        sys.settrace(None)
    return result, rows


def site_points():
    commit = 'results[scorer_name] = SampleScore(score=score_result, sample_id=sample.id, sample_metadata=sample.metadata, scorer=registry_unqualified_name(scorer))'
    raw_call = 'result_scores.extend(compute_eval_scores(scores, unreduced_metrics, scorer_name, scorer_info, None))'
    reduced_call = 'result_scores.extend(compute_eval_scores(reduced_scores, reduced_metrics, scorer_name, scorer_info, reducer_display_nm))'
    p = {
        'score-decision': (RUN, '_task_run_sample_attempt', commit, 'before'),
        'score-commit': (RUN, '_task_run_sample_attempt', commit, 'after'),
        'raw-consumer': (RESULTS, 'compute_eval_scores_for_views', raw_call, 'before'),
        'classification-input': (RESULTS, 'scorer_for_metrics', 'sample_scores_with_values = []', 'after'),
        'classification-count': (RESULTS, 'scorer_for_metrics', 'unscored_samples = len(sample_scores) - len(sample_scores_with_values)', 'after'),
        'filtered-count': (RESULTS, 'scorer_for_metrics', 'scored_samples = len(sample_scores_with_values)', 'before'),
        'scored-count': (RESULTS, 'scorer_for_metrics', 'scored_samples = len(sample_scores_with_values)', 'after'),
        'metric-selected': (RESULTS, 'scorer_for_metrics', 'base_metric_name = registry_log_name(metric)', 'after'),
    }
    for view, expression in [('raw', raw_call), ('reduced', reduced_call)]:
        for point, position in [('input', 'before'), ('returned', 'after')]:
            p[view + '-' + point] = (RESULTS, 'compute_eval_scores_for_views', expression, position)
    for branch, expression in [('nonempty', 'metric_value = call_metric(metric, sample_scores_with_values)'),
                                ('empty', 'metric_value = empty_metric_value(metric)')]:
        for point, position in [('input', 'before'), ('returned', 'after')]:
            p['metric-' + branch + '-' + point] = (RESULTS, 'scorer_for_metrics', expression, position)
    return p


def source_points(root, path, function, expression):
    raw=(Path(root)/path).read_bytes()
    tree = ast.parse(raw)
    scope, = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function]
    expected = ast.dump(ast.parse(expression).body[0], include_attributes=False)
    matches=[n for n in ast.walk(scope) if isinstance(n,ast.stmt) and ast.dump(n,include_attributes=False)==expected]
    if len(matches) != 1:
        raise ValueError('Independent native point is absent or ambiguous')
    node=matches[0]
    module=compile(raw,str(Path(root)/path),'exec')
    code,=[c for c in module.co_consts if type(c) is CodeType and c.co_name==function]
    inside=[i for i in dis.get_instructions(code) if i.positions.lineno is not None
            and (node.lineno,node.col_offset)<=(i.positions.lineno,i.positions.col_offset)
            and (i.positions.end_lineno,i.positions.end_col_offset)<=(node.end_lineno,node.end_col_offset)
            and i.opname not in ('NOP','CACHE','RESUME','RETURN_GENERATOR')]
    if not inside:raise ValueError('No original statement-entry bytecode')
    return {node.lineno:dict(end=node.end_lineno,entry_offset=min(i.offset for i in inside))}


def point_rows(rows, path, function, points, position):
    selected = [r for r in rows if r['path'] == path and r['function'] == function]
    completed = set()
    for index, row in enumerate(selected):
        if row['event'] != 'line' or row['line'] not in points:
            continue
        spec=points[row['line']]
        end=spec['end'] if type(spec) is dict else spec
        if type(spec) is dict and row.get('offset')!=spec['entry_offset']:
            continue
        if position == 'before':
            previous = next((r for r in reversed(selected[:index]) if r['call'] == row['call']), None)
            if type(spec) is dict or previous is None or previous['event'] != 'line' or not row['line'] <= previous['line'] <= end:
                yield row
        else:
            following = next(((j, r) for j, r in enumerate(selected[index + 1:], index + 1)
                if r['call'] == row['call'] and (r['event'] != 'line' or not row['line'] <= r['line'] <= end)), None)
            if following and following[0] not in completed and following[1]['event'] in ('line', 'return'):
                completed.add(following[0])
                yield following[1]


def facts(site, row, run):
    s = row['locals']
    identity = dict(run=run, candidate='authored-inspect', phase='raw-score-handoff', attempt=1,
                    obligation='score', activation=0, scorer=s['scorer_name'], sample=0, epoch=0, view='raw', slot=0)
    if site in ['score-decision', 'score-commit']:
        score = s['score_result'] if site == 'score-decision' else s['results'][s['scorer_name']]['score']
        sample = score['metadata']['sample_id'] if site == 'score-decision' else s['results'][s['scorer_name']]['sample_id']
        return [dict(identity={**identity, 'sample': sample, 'epoch': score['metadata']['epoch']},
                     values=dict(raw=score['raw'], role=site))]
    if site == 'raw-consumer' or site in ['raw-input', 'raw-returned', 'reduced-input', 'reduced-returned']:
        view = 'raw' if site.startswith('raw') else 'reduced'
        samples = s['scores' if view == 'raw' else 'reduced_scores']
        if site != 'raw-consumer':
            identity.update(phase='consumer-call', activation=row['activation'], view=view)
        role = 'raw-consumer' if site == 'raw-consumer' else 'consumer-' + site.split('-')[1]
        return [dict(identity={**identity, 'sample': v['sample_id'], 'epoch': v['score']['metadata']['epoch'] if view == 'raw' else 0},
                     values=dict(raw=v['score']['raw'], role=role)) for v in samples]
    identity.update(phase='native-unscored-count', activation=row['activation'],
                    view=json.dumps(s['reducer_name'], sort_keys=True, separators=(',', ':'), ensure_ascii=False))
    if site == 'classification-input':
        return [dict(identity={**identity, 'slot': i}, values=dict(raw=v['score']['raw'], role=site))
                for i, v in enumerate(s['sample_scores'])]
    if site == 'classification-count':
        return [dict(identity=identity, values=dict(count=s['unscored_samples'], input_size=len(s['sample_scores']), role=site))]
    identity['phase'] = 'metric-population'
    if site in ['filtered-count', 'scored-count', 'metric-selected']:
        count = s['scored_samples'] if site == 'scored-count' else len(s['sample_scores_with_values'])
        return [dict(identity=identity, values=dict(count=count, role=site))]
    identity['phase'] = 'metric-call'
    return [dict(identity=identity, values=dict(count=len(s['sample_scores_with_values']), role='metric-' + site.rsplit('-', 1)[1]))]


def main(options):
    root = Path(options['native_root'])
    hashes = json.loads((Path(options['fixture_root']) / 'source-hashes.json').read_text())
    native = load_native(root, hashes)
    result, rows = trace_run(root, native, options['case'], options['work'], options['call_journal'])
    shutil.copytree(options['work'], options['retained_work'])
    with Path(options['raw_reference']).open('x', encoding='utf-8') as stream:
        json.dump(dict(native=result, traces=rows), stream, indent=2, allow_nan=False)
    mapped = {site: [f for row in point_rows(rows, path, function, source_points(root, path, function, expression), position)
                     for f in facts(site, row, options['run'])]
              for site, (path, function, expression, position) in site_points().items()}
    if any(n == 'zerorun_harness' or n.startswith('zerorun_harness.') for n in sys.modules):
        raise RuntimeError('Independent reference imported the framework')
    return dict(native=result, facts=mapped, traces=rows, framework_semantics_imported=False,
                native_function_frames=len({r['call'] for r in rows}),
                selected_sync_activations=len({r['activation'] for r in rows if r['activation']}))


if __name__ == '__main__':
    result = main(json.loads(Path(sys.argv[1]).read_text()))
    with Path(sys.argv[2]).open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
