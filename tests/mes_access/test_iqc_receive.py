from dataclasses import replace
import json
from urllib.parse import urlsplit, parse_qs
import pytest
from .conftest import implementation
from .test_transport import Wire, client
from .test_queries import response

PATH = '/orbbec/iqcReceive/iqcReceiveAction!query.action'

def test_iqc_receive_fixed_wire_and_scope(config):
    wire = Wire(); wire.responses.append((200, [], response()))
    c = client(replace(config, allowed_api_paths=(*config.allowed_api_paths, PATH)), wire)
    c.query('iqc_receive', {'inspNo': 'INSP-1'}, 1, 5)
    method, target, body, headers = wire.calls[-1]
    assert method == 'POST' and urlsplit(target).path == PATH
    assert json.loads(parse_qs(urlsplit(target).query)['paramJson'][0]) == {'inspNo':'INSP-1','startDate':'','endDate':'','pageNumber':1,'pageLimit':5}
    c.close()

@pytest.mark.parametrize('filters', [{}, {'inspNo':''}, {'inspNo':'X','url':'x'}, {'inspNo':'X','startDate':'2026-02-30'}])
def test_iqc_receive_invalid_before_io(config, filters):
    wire = Wire()
    c = client(replace(config, allowed_api_paths=(*config.allowed_api_paths, PATH)), wire)
    with pytest.raises(Exception) as err: c.query('iqc_receive', filters)
    assert err.value.code == 'MES_INVALID_QUERY' and not wire.calls

def test_iqc_receive_service_and_audit(config_file, raw_config, tmp_path):
    from .test_service import service
    raw_config['allowed_api_paths'].append(PATH)
    wire=Wire(); wire.responses.append((200, [], response([{'INSP_CODE':'INSP-PRIVATE','IQC_USER':'inspector'}])))
    def factory(config):
        assert json.loads((tmp_path/'audit.json').read_text())['events'][-1]['status']=='started'
        return client(config,wire)
    s=service(config_file,tmp_path,factory,raw_config)
    result=s.query('iqc_receive',{'inspNo':'INSP-PRIVATE'},actor_id='admin')
    assert result['source']=='native_mes' and result['rows'][0]['IQC_USER']=='inspector'
    audit=(tmp_path/'audit.json').read_text()
    assert 'INSP-PRIVATE' not in audit and 'inspector' not in audit

def test_iqc_receive_api_requires_scope_and_admin():
    from .test_api import BASE, install, private, ADMIN
    browser,s,_,_=install()
    route=BASE+'/interfaces/iqc_receive/query'
    assert private(browser.post(route,json={'filters':{'inspNo':'INSP-1'}})).status_code==200
    s.calls.clear()
    assert private(browser.post(route,json={'filters':{}})).status_code==422 and not s.calls
    browser,s,_,_=install({**ADMIN,'read_only':True})
    assert private(browser.post(route,json={'filters':{'inspNo':'INSP-1'}})).status_code==403 and not s.calls
