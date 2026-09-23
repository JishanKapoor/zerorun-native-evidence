"""Explicit raw-artifact and finite native phase attribution, no checker imports."""
import hashlib
import json
from pathlib import Path


def phase_attribution(terminal,selected):
    rows=[]
    for node,status in sorted(selected.items()):
        candidates=[f for f in terminal if f['values']['nodeid']==node and f['values']['word']==status]
        phases=sorted({f['identity']['phase'] for f in candidates})
        disposition='UNIQUE_NATIVE_PHASE' if len(phases)==1 else 'INCONCLUSIVE_PHASE_AMBIGUITY' if len(phases)>1 else 'NO_NATIVE_NODE_ATTRIBUTION'
        rows.append(dict(nodeid=node,native_parser_status=status,actual_native_phases=phases,
                         actual_terminal_occurrences=len(candidates),disposition=disposition))
    return rows


def applicable_records(records):
    return [r for r in records if r['evidence_ids'] and r['reasons'] not in
            (['no_applicable_disposition'],['native_rule_guard_not_applicable'])]


def verify_audit_outcomes(records,expected_ambiguities):
    """Only declared duplicated parser identities may remain inconclusive."""
    expected={(r['relationship'],r['obligation']) for r in expected_ambiguities}
    actual=set()
    for row in records:
        if row['status']=='CONFORMS':continue
        key=(row['relationship'],row['identity']['obligation'])
        if (row['status']!='INCONCLUSIVE' or row['reasons']!=['ambiguous_or_duplicate_native_identity']
                or key not in expected or key in actual):
            raise ValueError('Unexpected nonconforming native relationship: '+str(key))
        actual.add(key)
    if actual!=expected:raise ValueError('Expected native duplicate-identity ambiguity was erased')


def duplicate_evidence(reports,parser_facts):
    """Connect declared ambiguity to independently retained native operands."""
    result=[]
    for name,phases,statuses in [
        ('test_teardown_error',[('setup','passed'),('call','passed'),('teardown','failed')],['PASSED','ERROR']),
        ('test_two_phase_errors',[('setup','failed'),('teardown','failed')],['ERROR','ERROR'])]:
        node='test_native_controls.py::'+name
        actual_phases=[(r['when'],r['outcome']) for r in reports if r['event']=='test_report' and r['nodeid']==node]
        actual_statuses=[f['values']['raw'] for f in parser_facts if f['identity']['obligation']==node]
        if actual_phases!=phases or actual_statuses!=statuses:
            raise ValueError('Declared native duplicate premise differs: '+node)
        result.append(dict(nodeid=node,native_phase_reports=actual_phases,native_parser_decisions=actual_statuses,
                           parser_identity_has_test_phase=False))
    return result


def audit(reference,route_output):
    output=Path(route_output);native=reference['native']
    if native['pytest'] is None:return dict(qualification_only=True)
    stdout=(output/'pytest.stdout.txt').read_bytes();framed=(output/'swe-acquisition-input.txt').read_bytes()
    actual=next(v for k,v in native['swe']['artifacts'].items() if k.endswith('/test_output.txt'))
    provenance=native['pytest']['provenance']
    artifact_checks=dict(
        stdout_identity=hashlib.sha256(stdout).hexdigest()==provenance['stdout_sha256'],
        exact_declared_framing=framed==b'>>>>> Start Test Output\n'+stdout+b'\n>>>>> End Test Output\n',
        original_parser_input_identical=actual['text'].encode('utf-8')==framed,
        original_parser_input_digest=actual['sha256']==provenance['framed_sha256']==hashlib.sha256(framed).hexdigest())
    selected=reference['swe_facts']['selected-return']
    if len(selected)!=1:raise ValueError('Expected exactly one actual selected native parser return')
    mapping=json.loads(selected[0]['values']['raw'])
    attributed=phase_attribution(reference['pytest_facts']['terminal-decision'],mapping)
    ambiguous=[r for r in attributed if r['nodeid'].endswith('::test_two_phase_errors')]
    if len(ambiguous)!=1 or ambiguous[0]['actual_native_phases']!=['setup','teardown']:
        raise ValueError('Actual two-phase error ambiguity was erased')
    if ambiguous[0]['disposition']!='INCONCLUSIVE_PHASE_AMBIGUITY':raise ValueError('False unique native phase')
    duplicates=duplicate_evidence(native['pytest']['reports'],reference['swe_facts']['parser-decision'])
    return dict(artifact_checks=artifact_checks,native_phase_attribution=attributed,duplicate_identity_operands=duplicates,
        scope='Native terminal decisions and actual flattened parser status. No nonexistent phase or upstream retry identity inferred.')
