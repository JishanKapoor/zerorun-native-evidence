"""Standalone v2 recipe: one original EvalPlus parent invocation, no framework."""
import importlib.util
from pathlib import Path
import tempfile

KINDS = {
    'accept-exact':'decision','accept-tolerant':'decision','accept-polynomial':'decision',
    'caught-rejection':'decision','true-commit':'commit','false-commit':'commit',
    'progress-write':'progress','worker-loop-completed':'worker_state','worker-terminated':'worker_state',
    'native-child-started':'process_start','parent-raw-state':'parent_state',
    'parent-slice-progress':'parent_progress','parent-materialized-details':'materialized',
    'parent-returned-details':'returned_detail','parent-return':'parent',
    'terminal-progress-loop':'terminal_progress','terminal-progress-terminated':'terminal_progress',
    'progress-before-write':'progress_before',
}
RULE_ROLES = {
    'decision-requires-detail':('worker',),
    'decision-requires-progress':('worker',),
    'decision-preserved-in-shared-byte':('worker',),
    'commit-preserved-in-parent-element':('parent','worker'),
    'commit-requires-parent-element':('parent','worker'),
    'materialized-element-preserved-at-return':('parent',),
    'worker-progress-preserved-at-parent-slice':('parent','worker'),
    'parent-success-from-materialized-inventory':('parent',),
    'parent-failure-state-mapping':('parent',),
    'parent-timeout-state-mapping':('parent',),
}


def materialize(reference,case,run_id):
    raw = reference['journal']['parent'] + reference['journal']['worker']
    facts=[]
    indices={}
    for row in raw:
        if row['name'] in KINDS:
            indices.setdefault(row['name'],[]).append(len(facts))
            facts.append(dict(kind=KINDS[row['name']],identity=row['identity'],values=row['values']))
    returns=[row for row in raw if row['name']=='native-worker-return']
    finished=[row for row in raw if row['name']=='native-process-finished']
    entered=[row for row in raw if row['name']=='native-worker-entry']
    graph = (len(finished)==len(entered)==1 and
             entered[0]['pid']==finished[0]['values']['child_pid'] and
             entered[0]['parent_pid']==reference['parent_pid'])
    parent_complete = reference['exception'] is None and reference['returned'] is not None and not reference['parent_journal_lost']
    worker_complete = (graph and len(returns)==1 and returns[0]['values']['normal_return']
                       and not returns[0]['values']['journal_lost'] and
                       finished[0]['values']['cached_exitcode']==0)
    completion={'parent':parent_complete,'worker':worker_complete}
    batches=[]
    for raw_name,site in [('native-materialized-batch','parent-materialized-details'),
                          ('native-returned-batch','parent-returned-details')]:
        for batch in [row for row in raw if row['name']==raw_name]:
            batches.append(dict(site=site,identity={key:value for key,value in batch['identity'].items() if key!='obligation'},
                                size=batch['values']['size'],fact_indices=indices.get(site,[]),
                                complete=parent_complete))
    return dict(
        inventory=[dict(run=run_id,candidate=case['id'],obligation=i,phase='base',attempt=1) for i in range(len(case['inputs']))],
        facts=facts,native_complete={name:all(completion[role] for role in roles) for name,roles in RULE_ROLES.items()},
        native_batches=batches)


def observe(case,run_id,evidence_directory=None,native_sources=None):
    # This module and reference.py live beside the sealed original/ directory.
    # The standalone export hashes the full source tree before calling here.
    prepared=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_s8_independent_native_reference',prepared/'reference.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    def execute(output):
        reference=module.run(prepared,case,output,run_id,original_root=prepared,source_inventory=native_sources)
        if reference['framework_semantics_imported']:
            raise ValueError('Standalone original recipe imported framework semantics')
        return materialize(reference,case,run_id)
    if evidence_directory is not None:
        return execute(Path(evidence_directory))
    with tempfile.TemporaryDirectory(prefix='s8-native-export-') as directory:
        return execute(Path(directory)/'raw')
