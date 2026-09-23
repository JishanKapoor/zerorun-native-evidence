# SPDX-License-Identifier: MIT
"""Reconcile bounded native list batches without inferring lost elements."""
import copy

from .api import digest
from .declarative import (data_boundary,exact,require,seal,typed,validate_profile,
                          validate_observations)
from .binding import validate_binding


@data_boundary
def extract_batches(profile,binding,payloads):
    """Separate semantic events, batch completeness, and acquisition controls.

    Payloads come from a validated per-producer A4 journal. Completeness here is
    an additional premise; it never replaces independent transport/lifecycle.
    An unfinished or damaged batch retains events but cannot prove absence.
    """
    validate_binding(profile,binding)
    return reconcile_batches(profile,binding['sha256'],payloads,
                             source_sha=digest(binding['original_sources']))


@data_boundary
def reconcile_batches(profile,binding_sha,payloads,*,source_sha):
    """Replay retained batch controls, including the identity of an empty list."""
    p=validate_profile(profile)
    require(type(payloads) is list and len(payloads)<=32768,'Invalid batch payload inventory')
    events=[];controls=[];receipts=[];active={};seen=set()
    for raw in payloads:
        require(type(raw) is dict,'Malformed acquired payload')
        if raw.get('schema')=='zerorun-acquisition-lifecycle/1':
            controls.append(copy.deepcopy(raw));continue
        if raw.get('schema')=='zerorun-native-batch/1':
            exact(raw,['schema','site','producer','binding_sha256','batch','size','stage','identity'],'native batch control')
            site=raw['site'];pid=raw['producer'];ident=raw['batch']
            require(site in p['sites'] and 'batch' in p['sites'][site]
                    and raw['binding_sha256']==binding_sha
                    and type(pid) is int and pid>0 and type(ident) is int and ident>0
                    and type(raw['size']) is int and 0<=raw['size']<=p['sites'][site]['batch']['max_items']
                    and raw['stage'] in ('begin','end'),'Invalid native batch provenance')
            fields={k for k in p['identity']
                    if not (set(p['sites'][site]['projection'][k]) & {'ordinal','item'})}
            exact(raw['identity'],fields,'native batch group identity')
            require(all(typed(v,p['identity'][k]) for k,v in raw['identity'].items()),
                    'Invalid native batch identity type')
            key=(pid,ident)
            if raw['stage']=='begin':
                require(key not in seen,'Ambiguous/repeated native batch')
                if pid in active:
                    receipts.append(active.pop(pid))
                seen.add(key)
                active[pid]=dict(producer=pid,batch=ident,site=site,size=raw['size'],
                                 identity=copy.deepcopy(raw['identity']),complete=False,event_ids=[],ordinals=[])
            else:
                require(pid in active,'Native batch end without beginning')
                row=active.pop(pid)
                require((row['batch'],row['site'],row['size'],row['identity'])==
                        (ident,site,raw['size'],raw['identity']),
                        'Native batch ending changes its identity/population')
                row['complete']=row['ordinals']==list(range(row['size'])) and len(row['event_ids'])==row['size']
                receipts.append(row)
            continue
        require(raw.get('site') in p['sites'],'Undeclared acquired payload')
        event=copy.deepcopy(raw);spec=p['sites'][event['site']]
        pid=event['producer']
        if 'batch' in spec:
            require(pid in active and active[pid]['site']==event['site']
                    and event['binding_sha256']==binding_sha,
                    'Native batch element has no matching acquisition')
            if spec['batch'].get('ordinal') == 'acquisition':
                exact(event.get('acquisition'),['batch','ordinal'],'native acquisition identity')
                require(event['acquisition']['batch']==active[pid]['batch'],
                        'Native element acquisition belongs to another batch')
                ordinal=event['acquisition']['ordinal']
                require(type(ordinal) is int,'Invalid native acquisition ordinal')
            else:
                ordinal_fields=[k for k in p['identity'] if spec['projection'][k]=={'ordinal':True}]
                ordinal=event['identity'][ordinal_fields[0]]
                require(type(ordinal) is int and all(event['identity'][k]==ordinal for k in ordinal_fields),
                        'Native batch ordinal identity mismatch')
            require(all(event['identity'][k]==v and type(event['identity'][k]) is type(v)
                        for k,v in active[pid]['identity'].items()),'Native batch element changed group identity')
            active[pid]['event_ids'].append(event['id'])
            active[pid]['ordinals'].append(ordinal)
        else:
            # A later ordinary event cannot supply a lost end frame. Preserve
            # both its positive evidence and the explicitly unfinished batch.
            if pid in active:
                receipts.append(active.pop(pid))
        events.append(event)
    receipts.extend(active.values())
    # This validates event shapes/provenance/order only. It supplies no claimed
    # scientific inventory: evaluate separately checks the real declared case.
    validate_observations(p,dict(inventory=[e['identity'] for e in events],
                                 source_sha256=source_sha),events)
    require(all(e['binding_sha256']==binding_sha for e in events),
            'Native batch event belongs to another binding')
    return seal(dict(schema='zerorun-batch-acquisition/1',binding_sha256=binding_sha,
                     events=events,batches=receipts,acquisition_controls=controls))
