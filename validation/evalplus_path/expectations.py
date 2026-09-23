"""Declared development controls; never imported by adapters/native candidates."""

# A narrow set of directional controls, specified before native acquisition.
# Missing C2 consumers are explicitly INCONCLUSIVE; C1 carries absence claims.
EXPECTATIONS = [
    ('before','polynomial-accepted-continue','decision-requires-detail',0,'VIOLATION'),
    ('before','polynomial-accepted-continue','decision-requires-progress',0,'VIOLATION'),
    ('after','polynomial-accepted-continue','decision-requires-detail',0,'CONFORMS'),
    ('after','polynomial-accepted-continue','decision-requires-progress',0,'CONFORMS'),
    ('accepted-commit-omission','exact-pass','decision-requires-detail',0,'VIOLATION'),
    ('accepted-commit-omission','exact-pass','decision-requires-progress',0,'VIOLATION'),
    ('accepted-commit-omission','exact-pass','commit-requires-parent-element',1,'VIOLATION'),
    ('rejected-commit-omission','rejected-continuation','decision-requires-detail',0,'VIOLATION'),
    ('rejected-commit-omission','rejected-continuation','decision-requires-progress',0,'VIOLATION'),
    ('pre-decision-skip','skip-only','decision-requires-detail',0,'CONFORMS'),
    ('pre-decision-skip','skip-only','parent-success-from-materialized-inventory',None,'CONFORMS'),
    ('pre-decision-skip','skip-then-accept','commit-requires-parent-element',1,'VIOLATION'),
    ('parent-reordered','mixed-dispositions','materialized-element-preserved-at-return',0,'VIOLATION'),
    ('parent-reordered','mixed-dispositions','materialized-element-preserved-at-return',1,'VIOLATION'),
    ('parent-wrong-status','exact-pass','parent-success-from-materialized-inventory',None,'VIOLATION'),
    ('forced-timeout-state','exact-pass','parent-timeout-state-mapping',0,'CONFORMS'),
    ('after','external-parent-timeout','parent-timeout-state-mapping',0,'CONFORMS'),
    ('after','external-parent-timeout','decision-requires-detail',0,'INCONCLUSIVE'),
]


def check(audits, acquisitions):
    rows = []
    for variant,case,relation,index,expected in EXPECTATIONS:
        records = audits[variant+':'+case]['records']
        match = [r for r in records if r['relationship']==relation and
                 r['identity'].get('obligation')==index]
        rows.append(dict(case=variant+':'+case,relationship=relation,obligation=index,
                         expected=expected,actual=[r['status'] for r in match],
                         passed=len(match)==1 and match[0]['status']==expected))
    for case,expected in [('after:exact-pass',True),('wrong-progress:exact-pass',False),
                          ('before:polynomial-accepted-continue',False),
                          ('after:polynomial-accepted-continue',True)]:
        observed = next(r['arithmetic']['completed_count'] for r in acquisitions if r['id']==case)
        rows.append(dict(case=case,relationship='independent-counter-arithmetic',
                         expected=expected,actual=observed,passed=observed is expected,
                         scope='Secondary reference assertion, not an extra primary arithmetic operator'))
    return rows


def applicable_records(records):
    """Comprehensive witnessed census, including consumer-only uncertainty.

    The original main campaign retained a narrower producer-premise census.
    This reporting change keeps missing-producer unknowns when the actual
    consumer is witnessed; it never changes an engine classification or call.
    """
    return [row for row in records if row['evidence_ids'] and row['reasons'] not in
            (['no_applicable_disposition'], ['native_rule_guard_not_applicable'])]


def reporting_census(profile, audit, reference=None):
    """Independent native-domain partition; never change an engine verdict.

    Domain exclusions come from source identity or the raw independent native
    trace. Observer evidence/reason labels alone cannot prove nonapplicability.
    """
    rules={rule['id']:rule for rule in profile.get('rules',[])}
    facts=[] if reference is None else [fact for rows in reference['journal'].values() for fact in rows]
    domains={}
    for ident,rule in rules.items():
        sites={name:site for name,site in profile['sites'].items() if site['kind']==rule['producer']}
        consumers={name for name,site in profile['sites'].items() if site['kind']==rule['consumer']}
        guard=rule.get('guard')
        guard_sites={name for name,site in profile['sites'].items() if guard and site['kind']==guard['kind']}
        def index(names):
            groups={}
            for fact in facts:
                if fact['name'] in names:
                    key=tuple(fact['identity'].get(field) for field in rule['keys'])
                    groups.setdefault(key,[]).append(fact)
            return groups
        domains[ident]=(sites,index(sites),index(consumers),index(guard_sites))
    worker_returns=[fact for fact in facts if fact['name']=='native-worker-return']
    worker_closed=len(worker_returns)==1 and worker_returns[0]['values'].get('journal_lost') is False
    parent_closed=reference is not None and reference['parent_journal_lost'] is False and (
        reference['returned'] is not None or reference['exception'] is not None)
    decisions=[]
    for row in audit['records']:
        if reference is None:
            include,reason=True,'missing_independent_domain_evidence'
        else:
            rule=rules[row['relationship']];group=row['identity']
            sites,source_groups,target_groups,guard_groups=domains[row['relationship']]
            group_key=tuple(group[key] for key in rule['keys'])
            possible=[site for site in sites.values() if all(
                'literal' not in site['projection'][key] or site['projection'][key]['literal']==group[key]
                for key in rule['keys'])]
            raw_source=source_groups.get(group_key,[])
            source=[fact for fact in raw_source if rule['when'] is None or fact['values'][rule['when']['field']] in rule['when']['in']]
            target=target_groups.get(group_key,[])
            roles={site['producer_role'] for site in possible}
            guard=rule.get('guard');guards=guard_groups.get(group_key,[])
            if not possible:
                include,reason=False,'outside_source_literal_identity_domain'
            elif (reference['native_bank_calls']==0 and not reference['journal']['worker']
                  and parent_closed and reference['exception'] is not None
                  and len(facts)==1 and facts[0]['name']=='native-parent-exception'
                  and facts[0]['values']['exception']==reference['exception']):
                include,reason=False,'independent_zero_bank_preflight_control'
            elif guard and len(guards)!=1:
                include,reason=True,'independent_native_guard_unresolved'
            elif guard and guards[0]['values'][guard['field']] not in guard['in']:
                include,reason=False,'independent_native_guard_false'
            elif raw_source and not source:
                include,reason=False,'independent_native_disposition_not_selected'
            elif source or target:
                include,reason=True,'independent_native_witness'
            elif row['evidence_ids']:
                include,reason=True,'observed_evidence_without_independent_domain_exclusion'
            elif roles=={'worker'} and worker_closed:
                include,reason=False,'completed_independent_worker_has_no_applicable_producer'
            elif roles=={'parent'} and parent_closed:
                include,reason=False,'completed_independent_parent_has_no_applicable_producer'
            else:
                include,reason=True,'unclosed_native_domain_remains_inconclusive'
        decisions.append(dict(relationship=row['relationship'],identity=row['identity'],
                              include=include,reason=reason,status=row['status']))
    return decisions


def applicable(profile, audit, events, batch_receipts, reference=None):
    census=reporting_census(profile,audit,reference)
    return [row for row,decision in zip(audit['records'],census) if decision['include']]
