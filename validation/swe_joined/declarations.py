"""One-instance native parser/grading/writer/reader chain, without replay joins."""
import copy

if __package__:
    from . import internal_declarations as internal, reporting_declarations as reporting
else:
    import internal_declarations as internal
    import reporting_declarations as reporting

REVISIONS = internal.REVISIONS
GRADING, PARSER = internal.GRADING, internal.PARSER
WRITER, REPORTING = reporting.WRITER, reporting.REPORTING
SOURCES = [GRADING, PARSER, WRITER, REPORTING]
IDENTITY = reporting.IDENTITY
CANDIDATE = 'authored-joined'
REPORTING_SITES = {'writer-input', 'writer-write', 'writer-closed', 'reader-value',
    'derivation-completed-completed', 'derivation-reader', 'resolved-membership-resolved',
    'resolved-membership-unresolved', 'aggregate-input', 'aggregate-written', 'aggregate-closed'} | {
    category + '-' + point for category in ['completed', 'resolved', 'unresolved']
    for point in ['decision', 'commit', 'population', 'aggregate']}


def profile(version):
    p = copy.deepcopy(internal.profile(version))
    p.update(id='swe-joined-' + version, identity=IDENTITY.copy(),
             justification='Same-execution original parser, grading, report writer and downstream aggregate; one native instance')
    for site in p['sites'].values():
        site['projection']['instance'] = {'context': 'instance'}
        site['projection']['phase']['literal'] = 'native-' + site['projection']['phase']['literal']
    # This return is the actual object returned to run_instance's report local.
    p['sites']['report-return']['projection'].update(phase={'literal': 'handoff'}, obligation={'literal': 'report'})
    for rule in p['rules']:
        rule['keys'].insert(2, 'instance')
    list_sites = []
    list_anchor = 'results = {FAIL_TO_PASS: {"success": f2p_success, "failure": f2p_failure}, PASS_TO_PASS: {"success": p2p_success, "failure": p2p_failure}}'
    for bank, native_key in [('f2p','FAIL_TO_PASS'),('p2p','PASS_TO_PASS')]:
        for outcome in ['success','failure']:
            for point, kind, position in [('input','grading-return','before'),('stored','grading-consumed','after')]:
                name = 'list-' + bank + '-' + outcome + '-' + point
                list_sites.append(name)
                value = {'local': bank + '_' + outcome, 'encoding': 'json'} if point == 'input' else {
                    'local': 'results', 'path': [{'index': native_key}, {'index': outcome}], 'encoding': 'json'}
                p['sites'][name] = dict(kind=kind, path=GRADING, function='get_eval_tests_report', anchor=list_anchor,
                    position=position, multiplicity=1, projection=dict(run={'context':'run'}, candidate={'context':'candidate'},
                        instance={'context':'instance'}, phase={'literal':'native-list-report'},
                        obligation={'literal':native_key + ':' + outcome}, attempt={'literal':1}, raw=value, role={'literal':'list'}),
                    justification='Observe the actual committed native list and its stored grading-report field around original construction')
    p['rules'].append(dict(id='native-commit-lists-report-preserved', check='C2', producer='grading-return', consumer='grading-consumed',
        keys=list(IDENTITY), when={'field':'role','in':['list']}, source_field='raw', target_field='raw', operator='identity',
        statuses=[], target_mapping=None, requires=list_sites,
        justification='Actual F2P/P2P success/failure lists must be preserved in the original grading report dictionary'))
    r = reporting.profile(version)
    chosen = {name: site for name, site in r['sites'].items() if name in REPORTING_SITES}
    kinds = {site['kind'] for site in chosen.values()}
    p['sites'].update(chosen)
    p['facts'].update({name: fields for name, fields in r['facts'].items() if name in kinds})
    for rule in r['rules']:
        if rule['producer'] in kinds and rule['consumer'] in kinds:
            rule['requires'] = [name for name in rule['requires'] if name in REPORTING_SITES]
            p['rules'].append(rule)
    for name, kind, values, phase, obligation, types in [
        ('tests-embedded', 'tests-embedded', {'raw': {'local': 'report_map', 'path': [{'index_local': 'instance_id'}, {'index': 'tests_status'}], 'encoding': 'json'}, 'role': {'literal': 'report'}},
         'native-pipeline', '@artifact', {'raw': 'str', 'role': 'str'}),
        ('resolution-embedded', 'resolution-embedded', {'raw': {'local': 'report_map', 'path': [{'index_local': 'instance_id'}, {'index': 'resolved'}]}, 'role': {'literal': 'reported-resolution'}},
         'native-resolution', 'PASS_TO_PASS', {'raw': 'bool', 'role': 'str'}),
    ]:
        p['facts'][kind] = types
        p['sites'][name] = dict(kind=kind, path=GRADING, function='get_eval_report',
            anchor='report_map[instance_id]["tests_status"] = report', position='after', multiplicity=1,
            projection=dict(run={'context': 'run'}, candidate={'context': 'candidate'}, instance={'local': 'instance_id'},
                phase={'literal': phase}, obligation={'literal': obligation}, attempt={'literal': 1}, **values),
            justification='Read the actual native report-map field after its original assignment')
    for name, producer, consumer, role, requires in [
        ('grading-embedded-preserved', 'grading-consumed', 'tests-embedded', 'report', ['grading-consumed', 'tests-embedded']),
        ('native-report-writer-preserved', 'report-return', 'writer-input', 'serialized', ['report-return', 'writer-input']),
    ]:
        p['rules'].append(dict(id=name, check='C2', producer=producer, consumer=consumer, keys=list(IDENTITY),
            when={'field': 'role', 'in': [role]}, source_field='raw', target_field='raw', operator='identity',
            statuses=[], target_mapping=None, requires=requires,
            justification='Same-invocation native object consumption across the original call/assignment boundary'))
    p['rules'].append(dict(id='native-resolution-report-preserved', check='C3', producer='resolution', consumer='resolution-embedded',
        keys=list(IDENTITY), when={'field': 'role', 'in': ['resolution']}, source_field='raw', target_field='raw',
        operator='all_in', statuses=['RESOLVED_FULL'], target_mapping=None,
        requires=['resolution-full', 'resolution-partial', 'resolution-no', 'resolution-embedded'],
        justification='Original get_eval_report sets resolved only when its actual native resolution is RESOLVED_FULL'))
    return p


def case_definitions():
    cases = []
    for case in internal.case_definitions():
        f2p, p2p = internal.F2P, internal.P2P
        repairs = [f2p]
        lines = [status + ' ' + name for name, status in zip([f2p, p2p], case['statuses']) if status]
        if 'second_repair' in case:
            repairs.append('tests/test_control.py::test_second_repair')
            lines.append(case['second_repair'] + ' ' + repairs[-1])
        if case.get('extra'):
            lines.append(case['extra'])
        body = '\n'.join(lines) + '\n'
        start, end = '>>>>> Start Test Output\n', '>>>>> End Test Output\n'
        content = body if case['layout'] == 'missing' else body + start + 'runner\n' + end if case['layout'] == 'outside' else start + body + end
        if case['layout'] == 'bad':
            content += '>>>>> Tests Timed Out\n'
        item = dict(id='a', log=content, fail_to_pass=repairs, pass_to_pass=[p2p])
        if case.get('patch_is_none'):
            item['patch'] = None
        cases.append(dict(id=case['id'], instances=[item]))
    for name, key, value in [('changed-file', 'tamper', 'flip-resolved'), ('truncated-file', 'tamper', 'truncate-json'),
                             ('write-denied', 'unwritable', True)]:
        item = copy.deepcopy(cases[0]['instances'][0])
        item[key] = value
        cases.append(dict(id=name, instances=[item]))
    cases.append(dict(id='no-native-call', instances=[]))
    return cases


def case_inventory(case, run):
    if not case['instances']:
        return []
    item, = case['instances']
    result = []

    def add(phase, obligation, attempt=1, instance='a'):
        row = dict(run=run, candidate=CANDIDATE, instance=instance, phase=phase, obligation=obligation, attempt=attempt)
        if row not in result:
            result.append(row)

    add('native-pipeline', '@artifact')
    add('native-pipeline', '@artifact', 2)
    add('native-parser', '@artifact')
    for test in item['fail_to_pass'] + item['pass_to_pass']:
        add('native-parser', test)
    if 'SKIPPED [1]' in item['log']:
        add('native-parser', '[1]')
    for bank, tests in [('f2p', item['fail_to_pass']), ('p2p', item['pass_to_pass'])]:
        for test in tests:
            add('native-' + bank, test)
    for operand in ['FAIL_TO_PASS', 'PASS_TO_PASS']:
        add('native-resolution', operand)
        for outcome in ['success', 'failure']:
            add('native-list-report', operand + ':' + outcome)
    add('handoff', 'report')
    for category in ['completed', 'resolved', 'unresolved']:
        add('category', category)
        add('aggregate', category, instance='@cohort')
    for operand in ['completed', 'decision']:
        add('resolution', operand)
    add('aggregate-file', 'report', instance='@cohort')
    return result
