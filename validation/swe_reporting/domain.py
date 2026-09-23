"""Executed-path census from independent native facts, never observer evidence.

This reporting-only domain does not supply expected statuses to the checker.
It retains original producer identities even if every observed event disappears.
Source-bound native guards/declared trigger values determine conditional scope.
"""
import json


def row_key(relationship,identity):
    return json.dumps([relationship,identity],sort_keys=True,separators=(',',':'))


def reference_domain(profile,facts,native_complete=None,inventory=None):
    if set(facts)!=set(profile['sites']):raise ValueError('Incomplete native reference site inventory')
    kinds={kind:[] for kind in profile['facts']}
    for site,items in facts.items():kinds[profile['sites'][site]['kind']].extend(items)
    rows={};inactive=[]
    for rule in profile['rules']:
        def identity(fact):return {key:fact['identity'][key] for key in rule['keys']}
        when=rule['when'];producer=kinds[rule['producer']]
        selected=[f for f in producer if when is None or f['values'][when['field']] in when['in']]
        # Unconditional handoffs remain in scope if an original consumer exists
        # but its original producer is missing. Conditional obligations require
        # an actual native trigger, independently acquired before observation.
        # An interrupted original operation cannot establish that an absent
        # conditional trigger was inapplicable. Retain its actual consumer
        # population as incomplete-premise obligations instead of discarding it.
        complete=True if native_complete is None else native_complete[rule['id']]
        members=selected+(kinds[rule['consumer']] if when is None or not complete else [])
        for fact in members:
            ident=identity(fact);key=row_key(rule['id'],ident)
            if 'guard' in rule:
                guard=rule['guard'];matching=[g for g in kinds[guard['kind']] if identity(g)==ident]
                if len(matching)==1 and matching[0]['values'][guard['field']] not in guard['in']:
                    inactive.append(dict(relationship=rule['id'],identity=ident));continue
            rows[key]=dict(relationship=rule['id'],identity=ident)
        if not complete:
            if inventory is None:raise ValueError('Interrupted native domain requires frozen inventory')
            # The original run cannot prove an unobserved obligation absent
            # after interruption. Retain every frozen identity compatible with
            # an admitted source producer and its literal trigger/identity fields.
            possible_sites=[]
            for site in profile['sites'].values():
                if site['kind'] not in [rule['producer'],rule['consumer']]:continue
                if site['kind']==rule['producer'] and when is not None:
                    selector=site['projection'][when['field']]
                    if 'literal' in selector and selector['literal'] not in when['in']:continue
                possible_sites.append(site)
            for declared in inventory:
                ident={name:declared[name] for name in rule['keys']}
                possible=any(all('literal' not in site['projection'][name]
                    or site['projection'][name]['literal']==value for name,value in ident.items()) for site in possible_sites)
                if possible:
                    key=row_key(rule['id'],ident)
                    rows.setdefault(key,dict(relationship=rule['id'],identity=ident,
                        basis='unresolved_source_compatible_domain_after_original_native_interruption'))
    return dict(schema='native-reference-domain/1',basis='Independent original native facts; after interruption all frozen source-compatible identities remain; no observed events or checker statuses',
                rows=[rows[key] for key in sorted(rows)],inactive_native_guards=inactive,
                incomplete_original_rules=[] if native_complete is None else [name for name,complete in native_complete.items() if not complete])


def select_records(records,domain):
    keys={row_key(row['relationship'],row['identity']) for row in domain['rows']}
    selected=[row for row in records if row_key(row['relationship'],row['identity']) in keys]
    if len(selected)!=len(keys):raise ValueError('Native reference domain missing or duplicated in checker inventory')
    return selected


def census(records,domain):
    keys={row_key(row['relationship'],row['identity']) for row in domain['rows']}
    counts={};excluded=[]
    for row in records:
        if row_key(row['relationship'],row['identity']) in keys:continue
        reason=('incompatible_with_original_source_literal_identity_domain' if row['relationship'] in domain['incomplete_original_rules']
                else 'outside_independently_completed_native_execution_domain')
        counts[reason]=counts.get(reason,0)+1
        excluded.append(dict(relationship=row['relationship'],identity=row['identity'],
                             classification=reason,retained_checker_status=row['status'],retained_checker_reasons=row['reasons']))
    return dict(domain=domain,excluded_counts=counts,excluded=excluded)
