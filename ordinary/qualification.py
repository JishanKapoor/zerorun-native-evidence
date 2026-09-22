"""Separate conventional qualification route; no production/monitor imports."""
import checks
def agreement(record):
    ref=record['native_reference'];obs=record['observation']
    if ref is None:return None
    if record['family']=='swe':
        a=ref.get('selected');b=obs.get('selected')
        return a==b if type(a) is dict and type(b) is dict else None
    values=obs.get('state')
    if type(values) is not dict:return None
    details=values.get('details');progress=values.get('progress');status=values.get('worker_status')
    rd=ref.get('details');grade=ref.get('grade')
    if type(rd) is not list or any(type(x) is not bool for x in rd) or grade not in ['pass','fail','timeout']:return None
    if type(details) is not list or type(progress) is not int or not 0<=progress<=len(details) or type(status) is not int or status not in [0,1]:return None
    if obs.get('health',{}).get('native_complete') is not True:return None
    expected='fail'
    if status==0 and progress==len(details) and False not in details:expected='pass'
    return rd==details[:progress] and grade==expected
def qualify(record,source_hashes):
    family=record['family'];obs=record['observation'];source=record['provenance']['source_sha256']
    if source not in source_hashes[family] or source!=obs.get('source_sha256'):return {'status':'UNSUPPORTED','relationship_status':'UNSUPPORTED','native_agreement':None}
    relationship=getattr(checks,family)(obs);same=agreement(record)
    answer='INCONCLUSIVE' if same is False and relationship in ['CONFORMS','VIOLATION'] else relationship
    return {'status':answer,'relationship_status':relationship,'native_agreement':same}
