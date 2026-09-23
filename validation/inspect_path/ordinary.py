"""Direct original trace assertions without the framework relationship engine."""
from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).parent))
if __package__:
    from .reference import site_points, source_points, point_rows
else:
    from reference import site_points, source_points, point_rows


def check(reference, root):
    traces=reference['traces']
    def observations(site):
        path,function,expression,position=site_points()[site]
        return list(point_rows(traces,path,function,source_points(root,path,function,expression),position))
    decisions,commits,consumed={},{},{}
    for row in observations('score-decision'):
        s=row['locals'];score=s['score_result'];key=(s['scorer_name'],score['metadata']['sample_id'],score['metadata']['epoch'])
        if key in decisions:raise ValueError('Duplicate actual scorer decision identity')
        decisions[key]=score['raw']
    for row in observations('score-commit'):
        s=row['locals'];sample=s['results'][s['scorer_name']];score=sample['score'];key=(s['scorer_name'],sample['sample_id'],score['metadata']['epoch'])
        if key in commits:raise ValueError('Duplicate actual scorer commitment identity')
        commits[key]=score['raw']
    for row in observations('raw-consumer'):
        s=row['locals']
        for sample in s['scores']:
            score=sample['score'];key=(s['scorer_name'],sample['sample_id'],score['metadata']['epoch'])
            if key in consumed:raise ValueError('Duplicate actual raw consumer sample identity')
            consumed[key]=score['raw']
    checks=[dict(id='original-decision-commit-complete-map',passed=decisions==commits,operands=len(decisions)),
            dict(id='original-commit-raw-consumer-complete-map',passed=commits==consumed,operands=len(commits))]
    for row in observations('scored-count'):
        s=row['locals'];incoming=s['sample_scores'];selected=s['sample_scores_with_values']
        actual_numeric=[v for v in incoming if v['score']['raw']!='NaN']
        checks.append(dict(id='actual-filtered-native-population',activation=row['activation'],
            passed=(selected==actual_numeric and s['scored_samples']==len(selected)
                    and s['unscored_samples']==len(incoming)-len(selected)),operands=len(incoming)))
    calls=[]
    for branch in ['empty','nonempty']:
        before=observations('metric-'+branch+'-input');after=observations('metric-'+branch+'-returned')
        def key(r):return (r['activation'],r['locals']['key'])
        left={key(r):r['locals']['sample_scores_with_values'] for r in before}
        right={key(r):r['locals']['sample_scores_with_values'] for r in after}
        calls.append(dict(id='actual-'+branch+'-metric-call-population',passed=left==right,
                          native_calls=len(left),unique=len(left)==len(before)==len(after)))
    for view in ['raw','reduced']:
        field='scores' if view=='raw' else 'reduced_scores'
        left={r['activation']:r['locals'][field] for r in observations(view+'-input')}
        right={r['activation']:r['locals'][field] for r in observations(view+'-returned')}
        checks.append(dict(id='actual-'+view+'-consumer-preservation',passed=left==right,native_calls=len(left)))
    return dict(checks=checks,metric_calls=calls,applicable_decisions=len(decisions),
                source='Original raw trace and native stored objects; no production mapper/checker oracle')
