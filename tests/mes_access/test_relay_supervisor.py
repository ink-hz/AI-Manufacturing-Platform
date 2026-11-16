import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('mes_supervisor_test',Path(__file__).parents[2]/'scripts'/'sap_relay_supervisor.py')
s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
def test_mes_profile_is_closed_and_sap_remains_default():
    settings={'ssh_identity':'/private/id','ssh_known_hosts':'/private/hosts','ssh_host':'host'}
    assert '/sap-relay/' in s.tunnel_argv(settings,'r-'+'a'*16+'.sock',1234)[-2]
    assert '/mes-relay/' in s.tunnel_argv(settings,'r-'+'a'*16+'.sock',1234,profile=s.MES_PROFILE)[-2]
    assert "-F" in s.ssh_base_argv(settings) and 'none' in s.ssh_base_argv(settings)
    with pytest.raises(ValueError):s.tunnel_argv(settings,'r-'+'a'*16+'.sock',1234,profile=object())
def test_main_accepts_static_profile_and_argv(capsys):
    with pytest.raises(SystemExit) as exc:s.main(['--help'],profile=s.MES_PROFILE)
    assert exc.value.code==0
def test_mes_settings_cannot_select_sap_or_arbitrary_remote_directory(tmp_path):
    import json
    from .test_relay_protocol import CONTEXT
    def private(name,text):
        p=tmp_path/name;p.write_text(text);p.chmod(0o600);return str(p)
    settings=dict(version=1,ssh_host='relay.example.com',ssh_user='root',ssh_identity=private('key','private'),ssh_known_hosts=private('hosts','public'),gateway_ready=str(tmp_path/'ready'),token_path=private('token','a'*64),remote_directory=s.MES_PROFILE.directory,expected_context=CONTEXT)
    path=private('settings',json.dumps(settings))
    assert s.load_settings(path,profile=s.MES_PROFILE)==settings
    with pytest.raises(ValueError):s.load_settings(path)
    for directory in (s.REMOTE_DIRECTORY,'/tmp/bridge'):
        settings['remote_directory']=directory;Path(path).write_text(json.dumps(settings))
        with pytest.raises(ValueError):s.load_settings(path,profile=s.MES_PROFILE)

def test_mes_remote_program_has_only_fixed_mes_path(tmp_path):
    import json,subprocess
    from .test_relay_protocol import CONTEXT
    calls=[]
    def runner(argv,**kwargs):
        calls.append(argv)
        assert s.MES_PROFILE.directory in argv[-1]
        assert s.REMOTE_DIRECTORY not in argv[-1]
        return subprocess.CompletedProcess(argv,0,json.dumps({'ready':True,'context':CONTEXT,'socketname':'r-'+'a'*16+'.sock'}).encode())
    s.remote_action({'ssh_host':'host','ssh_identity':'/key','ssh_known_hosts':'/hosts','expected_context':CONTEXT},'activate','r-'+'a'*16+'.sock',runner,profile=s.MES_PROFILE)
    assert len(calls)==1
