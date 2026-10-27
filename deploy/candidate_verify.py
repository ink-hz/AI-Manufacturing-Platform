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

class Auth:
    route_prefix='/';cookie_name='manufacturing_candidate_session';csrf_cookie_name='manufacturing_candidate_csrf';public_base_url='https://manufacturing-candidate.invalid'
    role=Role.PLATFORM_OWNER;stale=False;revoked=False
    def authenticate(self,token):
        if token!='synthetic-candidate-session' or self.revoked:return None
        return AuthContext(UUID('11111111-1111-4111-8111-111111111111'),self.role,UUID('22222222-2222-4222-8222-222222222222'),self.stale),'synthetic-candidate-csrf'
    def hard_stale_audit(self,*args):pass

auth=Auth()
def app():
    instance=FastAPI();instance.include_router(build_manufacturing_router())
    instance.add_middleware(IdentitySecurityMiddleware,auth=auth,authorization=AuthorizationService(None),public_assets=frozenset(),routes=tuple(instance.router.routes))
    return instance

client=TestClient(app(),base_url=auth.public_base_url)
prefix='/api/v1/manufacturing';stage=prefix+'/lines/oem/stages/S4'
def check(response,status):
    assert response.status_code==status,(status,response.status_code,response.text[:120])
    assert 'no-store' in response.headers.get('cache-control','')
    return response

check(client.get(prefix+'/catalog'),401)
client.cookies.set(auth.cookie_name,'synthetic-candidate-session');client.cookies.set(auth.csrf_cookie_name,'synthetic-candidate-csrf')
assert check(client.get(prefix+'/access'),200).json()['allowed']
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
auth.stale=True;check(client.get(stage),200);check(client.put(stage,json={**body,'expected_version':1},headers=headers),503)
auth.stale=False;auth.role=Role.MEMBER;check(client.get(stage),403)
auth.role=Role.PLATFORM_OWNER
response=client.put(stage,content=b'\xff',headers={**headers,'Content-Type':'application/json'})
assert response.status_code in {400,422} and 'no-store' in response.headers.get('cache-control','')
# New router/repository object on the same SQLite file must retain records.
with TestClient(app(),base_url=auth.public_base_url) as second:
    second.cookies.set(auth.cookie_name,'synthetic-candidate-session')
    assert check(second.get(stage),200).json()['record']['version']==1
    assert check(second.get(stage),200).json()['tasks'][0]['completed']
auth.revoked=True;check(client.get(stage),401)
print(json.dumps({'passed':True,'authentication':'synthetic_ASGI_with_real_middleware_authorization_csrf','persistence':'disposable_SQLite_reopen','business_lines':3,'business_relationships':'registered_not_connected','production_business_writes':0,'network_calls':0,'browser_acceptance':'not_run'}))
