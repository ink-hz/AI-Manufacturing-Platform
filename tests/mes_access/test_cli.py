"""Local command guards use an inert service and never contact MES."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / 'scripts' / 'verify_mes_access.py'
SECRET = 'private-business-record-password'


@pytest.fixture
def cli(monkeypatch):
    if not SCRIPT.is_file(): pytest.fail('MES CLI implementation is missing')
    spec = importlib.util.spec_from_file_location('mes_cli_under_test', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []
    class Service:
        def status(self): return {'source':'native_mes','enabled':True,'password':SECRET}
        def interfaces(self): return {'interfaces':[{'interface':'order_materials','max_page_size':5,'body':SECRET}]}
        def diagnose(self, actor_id):
            calls.append(('diagnose', actor_id))
            return {'authentication_verified':True, 'body':SECRET}
        def query(self, interface, filters, page, page_size, actor_id):
            calls.append(('query',interface,filters,page,page_size,actor_id))
            return {'interface':interface,'rows':[{'private':SECRET}], 'total':1, 'page':page, 'page_size':page_size,
                    'authentication_verified':True,'business_query_succeeded':True,'body':SECRET}
    def build(config, audit):
        calls.append(('build',config,audit))
        return Service()
    monkeypatch.setattr(module, 'build_mes_access_service', build)
    return module, calls


@pytest.mark.parametrize('arguments', [
    ['diagnose'], ['query','--interface','order_materials'],
    ['query','--live'], ['query','--live','--interface','arbitrary'],
    ['query','--live','--interface','order_materials','--filters','null'],
    ['query','--live','--interface','order_materials','--filters','{"shopOrder":true}'],
    ['query','--live','--interface','order_materials','--filters','{"url":"private"}'],
    ['query','--live','--interface','order_materials','--filters','{"shopOrder":"A","shopOrder":"B"}'],
    ['query','--live','--interface','order_materials','--page','0'],
    ['query','--live','--interface','order_materials','--page-size','6'],
    ['query','--live','--interface','order_materials','--filters',' ' * 4097],
    ['status','--password','secret'], ['status','--interface','order_materials'],
])
def test_invalid_commands_fail_before_builder(cli, arguments, capsys):
    module, calls = cli
    with pytest.raises(SystemExit) as error:
        module.main(arguments + ['--config','/private/config','--audit','/private/audit'])
    assert error.value.code == 2
    assert not calls
    captured = capsys.readouterr()
    assert 'secret' not in captured.out + captured.err


@pytest.mark.parametrize('config,audit', [('relative','/private/audit'),('/private/config','relative')])
def test_paths_must_be_absolute_before_builder(cli, config, audit):
    module, calls = cli
    with pytest.raises(SystemExit): module.main(['status','--config',config,'--audit',audit])
    assert not calls


@pytest.mark.parametrize('operation,options', [('status',[]),('interfaces',[]),('diagnose',['--live']),
    ('query',['--live','--interface','order_materials','--filters','{"shopOrder":"WO-1"}','--page','2','--page-size','3'])])
def test_default_output_omits_business_rows_and_raw_body(cli, operation, options, capsys):
    module, calls = cli
    assert module.main([operation,'--config','/private/config','--audit','/private/audit',*options]) == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert SECRET not in output
    assert 'rows' not in result and 'body' not in result
    assert calls[0] == ('build','/private/config','/private/audit')
    if operation == 'query':
        assert calls[1] == ('query','order_materials',{'shopOrder':'WO-1'},2,3,'local-cli')
        assert result['row_count'] == 1


@pytest.mark.parametrize('known', [False, True])
def test_cli_errors_emit_only_machine_code(cli, capsys, monkeypatch, known):
    from manufacturing_platform.mes_access.errors import MesAccessError
    module, _ = cli
    def fail(*args):
        error = MesAccessError('MES_TIMEOUT',504) if known else RuntimeError(SECRET)
        error.args = (SECRET,)
        raise error
    monkeypatch.setattr(module,'build_mes_access_service',fail)
    assert module.main(['status','--config','/private/config','--audit','/private/audit']) == 1
    assert json.loads(capsys.readouterr().out) == {'code':'MES_TIMEOUT' if known else 'MES_OPERATION_FAILED'}
