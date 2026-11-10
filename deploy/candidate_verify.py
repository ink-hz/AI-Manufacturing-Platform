"""Network-none candidate checks. All identities and business rows are disposable."""
from pathlib import Path
import hashlib
import json
import os
import sys
import subprocess
from uuid import UUID,uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.control_plane.authorization import AuthorizationService
from app.control_plane.middleware import IdentitySecurityMiddleware
from app.control_plane.models import AuthContext,Role
from app.manufacturing import build_manufacturing_router

expected=json.loads(sys.stdin.read())
assert os.getuid()==10001
if expected.get('native_sdk'):
    verify_installed_sdk(expected['native_sdk'])  # noqa: F821 - prepended pinned native_release helper
for arguments in [['git','--version'],['git','--no-lazy-fetch','--version']]:
    assert subprocess.run(arguments,capture_output=True,check=True).stdout.strip()==b'git version 2.50.1'
root=Path('/app/backend/app')
source={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and 'static' not in p.relative_to(root).parts and '__pycache__' not in p.parts and p.suffix!='.pyc'}
static={p.relative_to(root/'static').as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'static').rglob('*') if p.is_file()}
assert source==expected['expected_source'] and static==expected['expected_static'],'candidate_platform_content_mismatch'
business=Path('/opt/manufacturing');manifest=json.loads((business/'manifest.json').read_text())
assert manifest['commit']==expected['business_commit']
for name,digest in manifest['files'].items():assert hashlib.sha256((business/name).read_bytes()).hexdigest()==digest
assert os.statvfs(business).f_flag & os.ST_RDONLY
assert os.environ['PLATFORM_MANUFACTURING_DATABASE_PATH'].startswith('/tmp/')

# The same production app factory must register the feature; no hand-built router app.
HARNESS = r'''from pathlib import Path
import json,os,tempfile
from uuid import UUID
from fastapi.testclient import TestClient
from app.control_plane.authorization import AuthorizationService
from app.control_plane.models import IdentityMode
from app.control_plane.middleware import IdentitySecurityMiddleware
from app.control_plane.models import AuthContext,Role
from app.main import create_app
class Auth:
    mode=IdentityMode.PRODUCTION
    route_prefix='/';cookie_name='manufacturing_candidate_session';csrf_cookie_name='manufacturing_candidate_csrf';public_base_url='https://manufacturing-candidate.invalid'
    app_key='candidate-public-id';corp_id='candidate-corp-id'
    role=Role.PLATFORM_OWNER;stale=False;revoked=False
    @property
    def repository(self):return self
    def is_active_internal_user(self,uid):return uid==UUID('11111111-1111-4111-8111-111111111111') and not self.revoked
    def active_internal_user_profiles(self,ids):return [{'user_id':str(uid),'display_name':'Synthetic candidate'} for uid in ids if self.is_active_internal_user(uid)]
    def authenticate(self,token):
        if token!='synthetic-candidate-session' or self.revoked:return None
        return AuthContext(UUID('11111111-1111-4111-8111-111111111111'),self.role,UUID('22222222-2222-4222-8222-222222222222'),self.stale),'synthetic-candidate-csrf'
    def hard_stale_audit(self,*args):pass
class NoGrants:
    def permits(self,*args):return False
scratch=Path(tempfile.mkdtemp(prefix='manufacturing-harness-',dir='/tmp'))
(scratch/'registry.yaml').write_text('version: 1\nagents: []\n')
(scratch/'contract.json').write_text('{"bots": []}')
os.environ['PLATFORM_AGENT_BRAIN_ENABLED']='0'
os.environ['PLATFORM_STATIC_DIR']='/app/backend/app/static'
auth=Auth()
instance=create_app(registry_path=str(scratch/'registry.yaml'),cluster_contract_path=str(scratch/'contract.json'),start_poller=False,identity_auth=auth,identity_authorization=AuthorizationService(NoGrants()))
matched=[row for row in instance.user_middleware if row.cls is IdentitySecurityMiddleware]
assert len(matched)==1
assert isinstance(matched[0].kwargs['authorization'],AuthorizationService)
# Resolve the registered routing view used by the real security middleware.
from app.manufacturing_paths import MANUFACTURING_PREFIX,MANUFACTURING_ROUTES
registered={(method,route.path) for route in IdentitySecurityMiddleware._expand_included_routes(instance.routes) for method in getattr(route,'methods',[])}
assert all((method,MANUFACTURING_PREFIX+path) in registered for method,path in MANUFACTURING_ROUTES)
'''
exec(HARNESS)

client=TestClient(instance,base_url=auth.public_base_url)
prefix='/api/v1/manufacturing';stage=prefix+'/lines/oem/stages/S4'
def check(response,status):
    assert response.status_code==status,(status,response.status_code,response.text[:120])
    assert 'no-store' in response.headers.get('cache-control','')
    return response

for path in ['/catalog','/dashboard','/projects','/project-tasks','/handbook','/collaboration']:
    check(client.get(prefix+path),401)
check(client.get(prefix+'/assets/manufacturing.js',params={'release':'stale-candidate-release'}),401)
client.cookies.set(auth.cookie_name,'synthetic-candidate-session');client.cookies.set(auth.csrf_cookie_name,'synthetic-candidate-csrf')
assert check(client.get(prefix+'/access'),200).json()['allowed']
if expected.get('workflow'):
    import runpy
    private_checks=runpy.run_path('/candidate-fixture/controller.py')
    private_checks['verify_workflow_bootstrap'](client,check)
catalog=check(client.get(prefix+'/catalog'),200).json()
assert {row['id'] for row in catalog['lines']}=={'cameras','3d-printers','oem'}
assert check(client.get(stage),200).json()['record']['version']==0
headers={'Origin':auth.public_base_url,'X-CSRF-Token':'synthetic-candidate-csrf'}
body={'expected_version':0,'practice':'Candidate-only disposable workflow sample','participants':[{'name':'Candidate supplier','role':'supply','responsibility':'sample receipt'}],'handoffs':[{'name':'Design BOM','from_party':'Candidate design party','to_party':'Candidate manufacturing','version_reference':'candidate-v1','notes':'disposable'}],'systems':[{'name':'Candidate ERP registration','kind':'ERP','objects':'materials','maintainer':'candidate','method':'unknown','notes':'not connected'}]}
check(client.put(stage,json=body),403)
check(client.put(stage,json=body,headers={**headers,'Origin':'https://wrong.invalid'}),403)
check(client.put(stage,json=body,headers={**headers,'X-CSRF-Token':'wrong'}),403)
saved=check(client.put(stage,json=body,headers=headers),200).json();assert saved['version']==1
check(client.put(stage,json=body,headers=headers),409)
assert check(client.get(stage),200).json()['record']['participants']==body['participants']
assert check(client.get(prefix+'/lines/cameras/stages/S4'),200).json()['record']['practice']==''
task_body={'title':'Candidate-only disposable task','operation_id':str(uuid4())}
task=check(client.post(stage+'/tasks',json=task_body,headers=headers),200).json()
assert check(client.post(stage+'/tasks',json=task_body,headers=headers),200).json()==task
changed=check(client.patch(stage+'/tasks/'+task['id'],json={'title':task['title'],'completed':True,'expected_version':task['version']},headers=headers),200).json()
assert changed['completed'] and changed['version']==2
for name,mime in [('manufacturing.js','javascript'),('manufacturing.css','text/css')]:
    response=check(client.get(prefix+'/assets/'+name),200)
    assert mime in response.headers['content-type']
    assert hashlib.sha256(response.content).hexdigest()==manifest['files']['webui/dist/'+name]
    tagged=check(client.get(prefix+'/assets/'+name,params={'release':expected['business_commit']}),200)
    assert tagged.content==response.content
    check(client.get(prefix+'/assets/'+name,params={'release':'stale-candidate-release'}),409)
# Actual project workflows on isolated storage; legacy rows must remain unchanged.
legacy_snapshot=check(client.get(stage),200).json()
project_body={'name':'Disposable camera pilot','line_id':'cameras','owner':'Candidate coordinator','product':'Candidate camera','operation_id':str(uuid4())}
check(client.post(prefix+'/projects',json=project_body),403)
created=check(client.post(prefix+'/projects',json=project_body,headers=headers),200).json()
assert check(client.post(prefix+'/projects',json=project_body,headers=headers),200).json()==created
check(client.post(prefix+'/projects',json={**project_body,'owner':'Changed request'},headers=headers),409)
project_id=created['project']['id'];project_path=prefix+'/projects/'+project_id
second=check(client.post(prefix+'/projects',json={**project_body,'name':'Disposable OEM pilot','line_id':'oem','operation_id':str(uuid4())},headers=headers),200).json()
phase=created['stages'][0];phase_path=project_path+'/stages/'+phase['id']
fields=['status','owner','due_date','blocker','practice','participants','handoffs','systems']
def phase_body(value,**changes):
    return {**{k:value[k] for k in fields},'expected_version':value['version'],**changes}
phase=check(client.put(phase_path,json=phase_body(phase,status='doing',practice='Disposable project practice',owner='Candidate coordinator'),headers=headers),200).json()
phase=check(client.put(phase_path,json=phase_body(phase,status='blocked',blocker='Disposable BOM confirmation pending'),headers=headers),200).json()
assert check(client.get(prefix+'/dashboard'),200).json()['counts']['blocked_projects']==1
phase=check(client.put(phase_path,json=phase_body(phase,status='done',blocker=''),headers=headers),200).json()
phase=check(client.put(phase_path,json=phase_body(phase,status='doing'),headers=headers),200).json()
check(client.put(phase_path,json=phase_body(phase,expected_version=1),headers=headers),409)
item_body={'stage_id':phase['id'],'title':'Confirm disposable BOM revision','kind':'confirmation','owner':'Candidate engineer','priority':'high','operation_id':str(uuid4())}
item=check(client.post(project_path+'/tasks',json=item_body,headers=headers),200).json()
assert check(client.post(project_path+'/tasks',json=item_body,headers=headers),200).json()==item
assert check(client.get(prefix+'/dashboard'),200).json()['counts']['pending_confirmations']==1
item=check(client.patch(project_path+'/tasks/'+item['id'],json={'expected_version':item['version'],'status':'done'},headers=headers),200).json()
check(client.patch(project_path+'/tasks/'+item['id'],json={'expected_version':1,'status':'doing'},headers=headers),409)
assert check(client.get(prefix+'/dashboard'),200).json()['counts']['pending_confirmations']==0
assert check(client.get(stage),200).json()==legacy_snapshot
assert check(client.get(prefix+'/projects/'+second['project']['id']),200).json()['stages'][0]['practice']==''
archived=check(client.patch(project_path,json={'expected_version':1,'archived':True},headers=headers),200).json()
assert archived['project']['status']=='archived'
assert len(check(client.get(prefix+'/dashboard'),200).json()['projects'])==1
check(client.patch(project_path,json={'expected_version':archived['project']['version'],'archived':False},headers=headers),200)
# Engineering-to-readiness architecture, disposable and fully authorized.
arch=check(client.post(prefix+'/projects',json={'operation_id':str(uuid4()),'name':'Disposable readiness lifecycle','line_id':'cameras','owner':'Candidate engineer'},headers=headers),200).json()
arch_path=prefix+'/projects/'+arch['project']['id']
arch['stages'][0]=check(client.put(arch_path+'/stages/'+arch['stages'][0]['id'],json=phase_body(arch['stages'][0],status='doing'),headers=headers),200).json()
def control_write(method,path,body,status=200):
    return check(client.request(method,path,json={'operation_id':str(uuid4()),**body},headers=headers),status).json()
system_body={'name':'Disposable manual carrier','kind':'ERP','line_ids':['cameras'],'business_owner':'Candidate operations','it_owner':'Candidate IT','method':'manual','usage':'unverified'}
check(client.post(prefix+'/systems',json={'operation_id':str(uuid4()),**system_body}),403)
system=control_write('POST',prefix+'/systems',system_body)
assert system['recording_mode']=='manual'
control_write('POST',prefix+'/authorities',{'line_id':'cameras','object_type':'mbom','system_id':system['id'],'entry_point':'Candidate BOM register','owner':'Candidate engineer'})
basis_body={'title':'Candidate engineering basis','product_ref':'CAM-CANDIDATE','scope':'WO-CANDIDATE','provider':'Candidate engineering','owner':'Candidate engineer','internal_version':'A','items':[{'id':'bom','kind':'mbom','title':'Candidate MBOM','source_system_id':system['id'],'source_name':system['name'],'source_ref':'BOM-A','revision':'A','evidence':'CANDIDATE-DOC-A','owner':'Candidate engineer','status':'verified'}]}
basis=control_write('POST',arch_path+'/packages',basis_body)
def basis_action(value,action,**extra):
    return control_write('POST',arch_path+'/packages/'+value['id']+'/actions',{'expected_version':value['version'],'action':action,**extra})
basis=basis_action(basis_action(basis,'submit'),'verify')
handoff=control_write('POST',arch_path+'/handoffs',{'package_id':basis['id'],'from_party':'Candidate engineering','to_party':'Candidate assembly','owner':'Candidate engineer','method':'file'})
handoff_path=arch_path+'/handoffs/'+handoff['id']
handoff=control_write('PATCH',handoff_path,{'expected_version':handoff['version'],'action':'send','evidence':'CANDIDATE-SENT','occurred_at':'2026-10-27T05:00:00Z'})
receipt={'expected_version':handoff['version'],'action':'receive','received_revision':999,'evidence':'CANDIDATE-RECEIPT','occurred_at':'2026-10-27T06:00:00Z'}
control_write('PATCH',handoff_path,receipt,422)
handoff=control_write('PATCH',handoff_path,{**receipt,'received_revision':basis['revision']})
assert handoff['status']=='received'
checks=[{'id':'version','kind':'version','label':'Version basis','required':True,'owner':'Candidate engineer','status':'pending','package_item_id':'bom'},
        {'id':'calibration','kind':'equipment','label':'Fixture calibration','required':True,'owner':'Candidate engineer','status':'pending'},
        {'id':'first','kind':'first_article','label':'First article result','required':True,'owner':'Candidate quality','status':'pending'}]
ready_body={'title':'Candidate start preparation','package_id':basis['id'],'work_order_ref':'WO-CANDIDATE','scope':'Candidate batch','planned_use_date':'2026-10-27','owner':'Candidate engineer','required':True,'items':checks}
ready=control_write('POST',arch_path+'/readiness',ready_body)
blocked_checks=[{**row,'status':'blocked','reason':'Candidate evidence missing'} if row['id']=='version' else row for row in checks]
ready=control_write('PUT',arch_path+'/readiness/'+ready['id'],{'expected_version':ready['version'],'items':blocked_checks})
assert ready['status']=='blocked' and check(client.get(arch_path),200).json()['project']['status']=='blocked'
ready=control_write('PUT',arch_path+'/readiness/'+ready['id'],{'expected_version':ready['version'],'items':checks})
assert ready['status']=='pending' and check(client.get(arch_path),200).json()['project']['status']=='active'
linked=control_write('POST',arch_path+'/readiness/'+ready['id']+'/issues',{'item_id':'version','title':'Candidate version evidence','owner':'Candidate engineer'})
assert linked['source']=={'type':'readiness','id':ready['id'],'item_id':'version'}
for phase in arch['stages']:
    check(client.put(arch_path+'/stages/'+phase['id'],json=phase_body(phase,status='done'),headers=headers),200)
check(client.patch(arch_path+'/tasks/'+linked['id'],json={'expected_version':1,'status':'done'},headers=headers),200)
assert check(client.get(arch_path),200).json()['project']['status']=='active'
verified=[{**row,'status':'verified','source_ref':'CANDIDATE-SOURCE','evidence':'CANDIDATE-PROOF'} for row in checks]
verified[1]['valid_until']='2026-10-26';verified[2]['first_article_result']='passed'
control_write('PUT',arch_path+'/readiness/'+ready['id'],{'expected_version':ready['version'],'items':verified},422)
verified[1]['valid_until']='2026-12-31';verified[2]['first_article_result']='planned'
control_write('PUT',arch_path+'/readiness/'+ready['id'],{'expected_version':ready['version'],'items':verified},422)
verified[2]['first_article_result']='passed'
ready=control_write('PUT',arch_path+'/readiness/'+ready['id'],{'expected_version':ready['version'],'items':verified})
assert ready['status']=='complete' and check(client.get(arch_path),200).json()['project']['status']=='completed'
basis=basis_action(basis,'invalidate',reason='Candidate source approval withdrawn')
old=next(row for row in check(client.get(arch_path+'/controls'),200).json()['readiness'] if row['id']==ready['id'])
assert old['status']=='pending'
new_basis=basis_action(basis,'revise')
new_body=json.loads(json.dumps(basis_body));new_body['internal_version']='B';new_body['items'][0].update(revision='B',source_ref='BOM-B',evidence='CANDIDATE-DOC-B')
new_basis=control_write('PUT',arch_path+'/packages/'+new_basis['id'],{'expected_version':new_basis['version'],**new_body})
new_basis=basis_action(basis_action(new_basis,'submit'),'verify')
new_ready=control_write('POST',arch_path+'/readiness',{**ready_body,'package_id':new_basis['id'],'supersedes_id':old['id'],'supersedes_version':old['version']})
assert new_ready['status']=='pending'
new_ready=control_write('PUT',arch_path+'/readiness/'+new_ready['id'],{'expected_version':new_ready['version'],'items':verified})
controls=check(client.get(arch_path+'/controls'),200).json()
assert next(row for row in controls['readiness'] if row['id']==old['id'])['superseded_by']==new_ready['id']
assert new_ready['status']=='complete' and check(client.get(arch_path),200).json()['project']['status']=='completed'
assert all(row['actor_id']=='11111111-1111-4111-8111-111111111111' for row in controls['events'])

published_metadata=json.loads((business/'handbook-metadata.json').read_text())
for doc,path in [('handbook','docs/manufacturing-system-handbook.md'),('workflow','docs/workflows/manufacturing-process-overview.md')]:
    read=check(client.get(prefix+'/handbook',params={'document':doc,'release':expected['business_commit']}),200).json()
    assert read['source_path']==path and read['sha256']==manifest['files'][path]
    assert read['release']==expected['business_commit'] and read['updated_at']==published_metadata['files'][path]['updated_at']
    assert hashlib.sha256(read['markdown'].encode()).hexdigest()==read['sha256']
check(client.get(prefix+'/handbook',params={'release':'wrong-release'}),409)
auth.role=Role.PLATFORM_ADMIN
admin_project=check(client.get(project_path),200).json()
check(client.patch(project_path,json={'expected_version':admin_project['project']['version'],'summary':'Candidate administrator update'},headers=headers),200)
check(client.get(prefix+'/handbook'),200)
auth.role=Role.PLATFORM_OWNER
auth.stale=True
check(client.get(project_path),200);check(client.get(prefix+'/handbook'),200)
check(client.patch(project_path,json={'expected_version':2,'name':'Must not write'},headers=headers),503)
auth.stale=False;auth.role=Role.MEMBER
for path in ['/dashboard','/projects','/project-tasks','/handbook','/collaboration']:
    check(client.get(prefix+path),403)
auth.role=Role.PLATFORM_OWNER
auth.stale=True;check(client.get(stage),200);check(client.put(stage,json={**body,'expected_version':1},headers=headers),503)
auth.stale=False;auth.role=Role.MEMBER;check(client.get(stage),403)
auth.role=Role.PLATFORM_OWNER
response=client.put(stage,content=b'\xff',headers={**headers,'Content-Type':'application/json'})
assert response.status_code in {400,422} and 'no-store' in response.headers.get('cache-control','')
# Upgrade compatibility: old immutable source reads/writes the SAME disposable DB.
previous_root=os.environ.get('PLATFORM_MANUFACTURING_PREVIOUS_ROOT')
rollback_compatibility='not_applicable_initial'
if previous_root:
    previous=Path(previous_root)
    previous_manifest=json.loads((previous/'manifest.json').read_text())
    assert previous_manifest['commit']==os.environ['PLATFORM_MANUFACTURING_PREVIOUS_RELEASE']
    assert os.statvfs(previous).f_flag & os.ST_RDONLY
    for name,digest in previous_manifest['files'].items():
        assert hashlib.sha256((previous/name).read_bytes()).hexdigest()==digest
    legacy_reader=r"""import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(os.environ['PLATFORM_MANUFACTURING_PREVIOUS_ROOT'])/'src'))
from manufacturing_platform.project_repository import ProjectRepository
from manufacturing_platform.project_models import ProjectTaskWrite
from manufacturing_platform.catalog import load_catalog
repo=ProjectRepository(os.environ['PLATFORM_MANUFACTURING_DATABASE_PATH'],load_catalog())
pid,task_id=sys.argv[1:]
detail=repo.get(pid)
repo.list();repo.dashboard()
item=next(row for row in detail['tasks'] if row['id']==task_id)
repo.update_task(pid,task_id,ProjectTaskWrite(expected_version=item['version'],notes='Candidate previous-source roundtrip'),'Candidate rollback reader')
assert repo.get(pid)['tasks']
print('previous-source-current-db-ok')
"""
    assert subprocess.run([sys.executable,'-c',legacy_reader,arch['project']['id'],linked['id']],capture_output=True,check=True).stdout.strip()==b'previous-source-current-db-ok'
    forward=check(client.get(arch_path),200).json()
    forward_issue=next(row for row in forward['tasks'] if row['id']==linked['id'])
    assert forward_issue['source']=={'type':'readiness','id':old['id'],'item_id':'version'}
    assert forward_issue['notes']=='Candidate previous-source roundtrip'
    assert forward['project']['status']=='completed'
    rollback_compatibility='previous_immutable_source_read_write_current_disposable_database_then_forward'

# Close the first app's client, then reopen through the real adapter in a NEW process.
client.close()
reopen = HARNESS + r'''
c=TestClient(instance,base_url=auth.public_base_url)
c.cookies.set(auth.cookie_name,'synthetic-candidate-session')
r=c.get('/api/v1/manufacturing/lines/oem/stages/S4')
assert r.status_code==200
assert r.json()['record']['version']==1
assert r.json()['record']['participants'][0]['name']=='Candidate supplier'
assert r.json()['tasks'][0]['completed']
c.close()
print('process-restart-persistence-ok')
'''
reopen=reopen.replace("c.close()\nprint('process-restart-persistence-ok')", "r=c.get("+repr(project_path)+")\nassert r.status_code==200\nassert r.json()['stages'][0]['practice']=='Disposable project practice'\nassert r.json()['tasks'][0]['status']=='done'\nc.close()\nprint('process-restart-persistence-ok')")
reopen=reopen.replace("c.close()\nprint('process-restart-persistence-ok')", "r=c.get("+repr(arch_path+'/controls')+")\nassert r.status_code==200\nassert any(row['id']=="+repr(new_ready['id'])+" and row['status']=='complete' for row in r.json()['readiness'])\nassert any(row['superseded_by']=="+repr(new_ready['id'])+" for row in r.json()['readiness'])\nc.close()\nprint('process-restart-persistence-ok')")
restart_history="r=c.get("+repr(arch_path+'/controls')+")\nassert r.status_code==200\ndata=r.json()\nreceipt=next(row for row in data['handoffs'] if row['id']=="+repr(handoff['id'])+")\nassert {key:receipt[key] for key in ['status','package_id','package_revision','received_revision','evidence','occurred_at']}=="+repr({key:handoff[key] for key in ['status','package_id','package_revision','received_revision','evidence','occurred_at']})+"\nassert any(row['id']=="+repr(basis['id'])+" and row['status']=='invalid' and row['revision']==1 for row in data['packages'])\nassert any(row['id']=="+repr(new_basis['id'])+" and row['status']=='verified' and row['revision']==2 for row in data['packages'])\nassert any(row['action']=='receive' and row['snapshot']['id']=="+repr(handoff['id'])+" for row in data['events'])\nassert any(row['action']=='supersede' and row['snapshot']['id']=="+repr(old['id'])+" for row in data['events'])\n"
reopen=reopen.replace("c.close()\nprint('process-restart-persistence-ok')",restart_history+"c.close()\nprint('process-restart-persistence-ok')")
assert subprocess.run([sys.executable,'-c',reopen],capture_output=True,check=True).stdout.strip()==b'process-restart-persistence-ok'
client=TestClient(instance,base_url=auth.public_base_url)
client.cookies.set(auth.cookie_name,'synthetic-candidate-session')
auth.revoked=True;check(client.get(stage),401)
workflow_acceptance=None
if expected.get('workflow'):
    workflow_acceptance=private_checks['run_acceptance']()
print(json.dumps({'workflow_acceptance':workflow_acceptance,'passed':True,'authentication':'synthetic_ASGI_with_real_middleware_authorization_csrf','persistence':'disposable_SQLite_separate_process_restart','rollback_compatibility':rollback_compatibility,'application':'actual_app.main.create_app_routes','business_lines':3,'project_workflows':'create_phase_block_reopen_confirmation_archive_legacy_preservation','architecture_workflows':'systems_authority_frozen_versions_receipts_readiness_supersession_issue_audit','handbook':'exact_published_markdown_and_metadata','business_relationships':'registered_not_connected','production_business_writes':0,'network_calls':0,'browser_acceptance':'not_run'}))
