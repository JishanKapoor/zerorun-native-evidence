"""Finite original Inspect score commitments and actual consumer boundaries."""
RUN = 'inspect_ai/_eval/task/run.py'
RESULTS = 'inspect_ai/_eval/task/results.py'
METRIC = 'inspect_ai/scorer/_metric.py'
PIN = 'f9837f6c577da1bf89223f0575d4cb218940a79f'
IDENTITY = dict(run='str',candidate='str',phase='str',attempt='int',obligation='str',
                activation='int',scorer='str',sample='int',epoch='int',view='str',slot='int')
COMMIT = 'results[scorer_name] = SampleScore(score=score_result, sample_id=sample.id, sample_metadata=sample.metadata, scorer=registry_unqualified_name(scorer))'
RAW_CALL = 'result_scores.extend(compute_eval_scores(scores, unreduced_metrics, scorer_name, scorer_info, None))'
REDUCED_CALL = 'result_scores.extend(compute_eval_scores(reduced_scores, reduced_metrics, scorer_name, scorer_info, reducer_display_nm))'


def lit(value): return {'literal':value}
def stored(record,field): return {'stored':field,'record':record}
def local(name,*path,**options): return {'local':name,**({'path':list(path)} if path else {}),**options}
def item(*path,**options): return {'item':True,'path':list(path),**options}
def score_value(origin): return {**origin,'path':origin.get('path',[])+[stored('score','value')],'encoding':'number_json'}
def score_meta(origin,field): return {**origin,'path':origin.get('path',[])+[stored('score','metadata'),{'index':field}]}


def profile():
    p=dict(api='zerorun.extensions/1',id='inspect-native-path',version='1.0.0',identity=IDENTITY.copy(),facts={},sites={},rules=[],
           record_types={
               'score':dict(module='inspect_ai.scorer._metric',name='Score',path=METRIC,fields=['value','metadata']),
               'sample_score':dict(module='inspect_ai.scorer._metric',name='SampleScore',path=METRIC,fields=['score','sample_id','scorer'])},
           justification='Authored native original Inspect eval, stored score commitments, raw/reduced calls and bounded NaN-exclusion consistency')

    def site(name,kind,function,anchor,position,fields,types,*,phase,view=None,sample=None,epoch=None,activation=False,batch=None,ordinal=False):
        ident=dict(run={'context':'run'},candidate={'context':'candidate'},phase=lit(phase),attempt=lit(1),obligation=lit('score'),
            activation={'activation':True} if activation else lit(0),scorer=local('scorer_name'),
            sample=sample or lit(0),epoch=epoch or lit(0),view=view or lit('raw'),slot={'ordinal':True} if ordinal else lit(0))
        p['facts'][kind]=types
        spec=dict(kind=kind,path=RUN if function=='_task_run_sample_attempt' else RESULTS,function=function,
            anchor=anchor,position=position,multiplicity=1,projection={**ident,**fields},
            justification='Actual original native state at '+name)
        if batch:
            spec['batch']=dict(local=batch,max_items=6,**({} if ordinal else {'ordinal':'acquisition'}))
        p['sites'][name]=spec

    rawtype={'raw':'str','role':'str'}
    for name,kind,position,origin in [('score-decision','score-decision','before',local('score_result')),
                                    ('score-commit','score-commit','after',local('results',{'index_local':'scorer_name'},stored('sample_score','score')))]:
        sample=score_meta(origin,'sample_id') if position=='before' else local('results',{'index_local':'scorer_name'},stored('sample_score','sample_id'))
        site(name,kind,'_task_run_sample_attempt',COMMIT,position,dict(raw=score_value(origin),role=lit(kind)),rawtype,
            phase='raw-score-handoff',sample=sample,epoch=score_meta(origin,'epoch'))
    origin=item(stored('sample_score','score'))
    site('raw-consumer','raw-consumer','compute_eval_scores_for_views',RAW_CALL,'before',
        dict(raw=score_value(origin),role=lit('raw-consumer')),rawtype,phase='raw-score-handoff',
        sample=item(stored('sample_score','sample_id')),epoch=score_meta(origin,'epoch'),batch='scores')
    for view,anchor,collection in [('raw',RAW_CALL,'scores'),('reduced',REDUCED_CALL,'reduced_scores')]:
        for point,position in [('input','before'),('returned','after')]:
            kind='consumer-'+point
            site(view+'-'+point,kind,'compute_eval_scores_for_views',anchor,position,
                dict(raw=score_value(origin),role=lit(kind)),rawtype,phase='consumer-call',view=lit(view),
                sample=item(stored('sample_score','sample_id')),
                epoch=score_meta(origin,'epoch') if view=='raw' else lit(0),activation=True,batch=collection)
    # C3 uses native input ordinals as operand identities. They are not scientific
    # sample identities, and reduced Score metadata epochs are never used here.
    view=local('reducer_name',encoding='json')
    site('classification-input','classification-input','scorer_for_metrics','sample_scores_with_values = []','after',
        dict(raw=score_value(origin),role=lit('classification-input')),rawtype,phase='native-unscored-count',
        activation=True,view=view,batch='sample_scores',ordinal=True)
    site('classification-count','classification-count','scorer_for_metrics',
        'unscored_samples = len(sample_scores) - len(sample_scores_with_values)','after',
        dict(count=local('unscored_samples'),input_size=local('sample_scores',size=True),role=lit('classification-count')),{'count':'int','input_size':'int','role':'str'},
        phase='native-unscored-count',activation=True,view=view)
    for name,kind,anchor,position,projection in [
        ('filtered-count','filtered-count','scored_samples = len(sample_scores_with_values)','before',local('sample_scores_with_values',size=True)),
        ('scored-count','scored-count','scored_samples = len(sample_scores_with_values)','after',local('scored_samples')),
        ('metric-selected','metric-selected','base_metric_name = registry_log_name(metric)','after',local('sample_scores_with_values',size=True)),
    ]:
        site(name,kind,'scorer_for_metrics',anchor,position,dict(count=projection,role=lit(kind)),{'count':'int','role':'str'},
            phase='metric-population',activation=True,view=view)
    for branch,anchor in [('nonempty','metric_value = call_metric(metric, sample_scores_with_values)'),
                          ('empty','metric_value = empty_metric_value(metric)')]:
        for point,position in [('input','before'),('returned','after')]:
            kind='metric-'+point
            site('metric-'+branch+'-'+point,kind,'scorer_for_metrics',anchor,position,
                dict(count=local('sample_scores_with_values',size=True),role=lit(kind)),{'count':'int','role':'str'},
                phase='metric-call',activation=True,view=view)

    def rule(name,check,producer,consumer,field=None):
        p['rules'].append(dict(id=name,check=check,producer=producer,consumer=consumer,keys=list(IDENTITY),
            when={'field':'role','in':[producer]},source_field=field,target_field=field,
            operator='exists' if check=='C1' else 'identity',statuses=[],target_mapping=None,
            requires=[n for n,s in p['sites'].items() if s['kind'] in [producer,consumer]],
            justification='Preserve original native '+name))
    for label,producer,consumer,field in [('scorer-commit','score-decision','score-commit','raw'),
                                         ('committed-raw-input','score-commit','raw-consumer','raw'),
                                         ('consumer-call','consumer-input','consumer-returned','raw'),
                                         ('metric-call','metric-input','metric-returned','count')]:
        rule(label+'-required','C1',producer,consumer)
        rule(label+'-preserved','C2',producer,consumer,field)
    rule('filtered-cardinality-preserved','C2','filtered-count','scored-count','count')
    rule('selected-metric-population-preserved','C2','scored-count','metric-selected','count')
    p['rules'].append(dict(id='native-unscored-classification',check='C3',producer='classification-input',consumer='classification-count',
        keys=[k for k in IDENTITY if k!='slot'],when={'field':'role','in':['classification-input']},source_field='raw',target_field='count',
        operator='all_in',statuses=['0.0','0.5','1.0'],target_mapping={'true':[0],'false':[1,2],'incomplete':[]},
        guard={'kind':'classification-count','field':'input_size','in':[1,2,3,4,5,6]},
        inventory_policy='complete_batch_membership',requires=['classification-input','classification-count'],
        justification='For the frozen finite numeric/NaN fixture, all native input values are non-NaN iff native unscored_samples is zero; not metric arithmetic'))
    return p


def case_definitions():
    return [dict(id='a-before-b',order=['a','b']),dict(id='b-before-a',order=['b','a']),
            dict(id='empty-scoring',order=['a','b'],empty_scores=True),dict(id='no-native-call',order=[])]


def expected_populations(case):
    """Frozen authored membership, from the exposed native error/order fixture.

    This is an input-side coverage inventory, not an expected metric value or
    observer-derived population. Any unexpected native population fails the
    separate inventory assertion rather than silently shrinking this inventory.
    """
    if not case['order']:
        return {}
    if case.get('empty_scores'):
        return {which:dict(raw=[],reduced=[]) for which in ['a','b']}
    a = [(1,1),(2,1),(3,1),(1,2),(2,2),(3,2)]
    if case['order'] == ['b','a']:
        a.remove((2,1))
    return {'a':dict(raw=a,reduced=[(i,0) for i in ([1,2,3] if case['order']==['a','b'] else [1,3,2])]),
            'b':dict(raw=[(1,1),(3,1),(2,2),(3,2)],reduced=[(1,0),(3,0),(2,0)])}


def case_inventory(case, run):
    if not case['order']:
        return []
    rows = []
    populations = expected_populations(case)
    def identity(scorer,phase,activation=0,view='raw',sample=0,epoch=0,slot=0):
        return dict(run=run,candidate='authored-inspect',phase=phase,attempt=1,obligation='score',
                    activation=activation,scorer='scorer_'+scorer,sample=sample,epoch=epoch,view=view,slot=slot)
    for which in case['order']:
        rows.extend(identity(which,'raw-score-handoff',sample=s,epoch=e) for s,e in populations[which]['raw'])
    # Public score_display=False omits optional timer-based progress evaluation.
    # Final original eval_results still calls both actual native views per scorer.
    for first, empty in [(1,bool(case.get('empty_scores')))]:
        for offset,which in enumerate(case['order']):
            activation=first+3*offset
            for view,next_activation,native_view in [('reduced',activation+1,'"mean"'),('raw',activation+2,'null')]:
                population=[] if empty else populations[which][view]
                rows.extend(identity(which,'consumer-call',activation,view,s,e) for s,e in population)
                rows.extend(identity(which,'native-unscored-count',next_activation,native_view,slot=i)
                            for i in range(max(1,len(population))))
                rows.append(identity(which,'metric-population',next_activation,native_view))
                rows.append(identity(which,'metric-call',next_activation,native_view))
    return rows


def expected_site_identities(case, run):
    """Prospective exact witness membership, including truly empty activations."""
    inventory=case_inventory(case,run)
    result={s:[] for s in profile()['sites']}
    if not case['order']:
        return result
    for site in ['score-decision','score-commit','raw-consumer']:
        result[site]=[i for i in inventory if i['phase']=='raw-score-handoff']
    for view in ['raw','reduced']:
        for point in ['input','returned']:
            result[view+'-'+point]=[i for i in inventory if i['phase']=='consumer-call' and i['view']==view]
    result['classification-input']=[] if case.get('empty_scores') else [i for i in inventory if i['phase']=='native-unscored-count']
    result['classification-count']=[i for i in inventory if i['phase']=='native-unscored-count' and i['slot']==0]
    for site in ['filtered-count','scored-count','metric-selected']:
        result[site]=[i for i in inventory if i['phase']=='metric-population']
    for branch in ['empty','nonempty']:
        for point in ['input','returned']:
            result['metric-'+branch+'-'+point]=[i for i in inventory if i['phase']=='metric-call'
                and bool(case.get('empty_scores'))==(branch=='empty')]
    return result
