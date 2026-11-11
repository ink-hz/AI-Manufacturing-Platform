"""Source-reviewed read operations; callers never supply a path or action."""
from dataclasses import dataclass
from datetime import date
import re
from types import MappingProxyType

from .errors import MesAccessError


@dataclass(frozen=True)
class Interface:
    label: str
    path: str
    filters: tuple[str, ...]
    size_key: str = 'pageLimit'
    rows_key: str = 'page'
    encoding: str = 'param_json_url'
    fixed_fields: tuple[tuple[str, object], ...] = ()
    required_filters: tuple[str, ...] = ()
    pagination_mode: str = 'paged'


INTERFACES = MappingProxyType({
    'order_materials': Interface('ERP工单物料清单', '/venken/prodcpdb/prodcpdbAction!queryMshoporderresb.action', ('shopOrder',)),
    'order_operations': Interface('ERP工单工序', '/venken/prodcpdb/prodcpdbAction!queryMshoporderafvc.action', ('shopOrder',)),
    'material_priority': Interface('工单物料优先级及缺口', '/orbbec/orderItemGrade/orderItemGradeAction!query.action', ('shopOrder', 'itemNo'), fixed_fields=(('ignoreflag', False),)),
    'iqc_records': Interface('IQC检验单', '/venken/iqcTestInput/iqcTestInputAction!getList.action', ('IQC_NO', 'ITEM_NO', 'ITEM_LOT', 'startDate', 'endDate'), 'pageSize', 'iqcList'),
    'iqc_receive': Interface('IQC inspector receipt', '/orbbec/iqcReceive/iqcReceiveAction!query.action', ('inspNo', 'startDate', 'endDate'), required_filters=('inspNo',)),
    'iqc_inspections': Interface('IQC inspection detail report', '/orbbec/iqcInspection/iqcInspectionAction!query.action', ('date_start', 'date_end', 'item_no', 'vender', 'status', 'result'), encoding='json_body', fixed_fields=(('checkBox', ''),)),
    'production_reports': Interface('报工记录', '/venken/prodcpdb/prodcpdbAction!query.action', ('data02', 'vornr', 'begindate', 'enddate', 'flag', 'flag1')),
    'inventory_counts': Interface('盘点单（不是库存余额）', '/orbbec/wmsInventoryCheck/wmsInventoryCheckAction!query.action', ('statCode', 'initUser', 'status', 'warehouseNo', 'startDate', 'endDate')),
    # inventory.info.ctrl.js:53-55 owns this SELECT and the querySql body.
    # :SITE is bound by the MES session; callers cannot supply SQL or its binds.
    'warehouses': Interface('仓库（限量读取，总数未知）', '/orbbec/customCommon/customCommonAction!query.action', (),
        rows_key='DATA', encoding='json_body', pagination_mode='bounded_data',
        fixed_fields=(('querySql', 'SELECT VAREHOUSE_NO,VAREHOUSE_NAME FROM W_WAREHOUSE '
                       'WHERE SITE=:SITE AND ROWNUM<={row_limit} ORDER BY VAREHOUSE_NO ASC'),)),
    'inventory_options': Interface('指定仓库及物料的库存选项', '/orbbec/appointIssue/appointIssueAction!queryInventoryOptions.action',
        ('warehouseNo', 'itemNo', 'appointBatch', 'shippingSpace'), required_filters=('warehouseNo', 'itemNo')),
})
DATE_KEYS = frozenset({'startDate', 'endDate', 'begindate', 'enddate', 'date_start', 'date_end'})


def prepare_query(config, interface, filters=None, page=1, page_size=1):
    """Return a fresh fixed wire payload after all public inputs pass policy."""
    if type(interface) is not str or interface not in INTERFACES:
        raise MesAccessError('MES_INTERFACE_DENIED', 404)
    spec = INTERFACES[interface]
    if spec.path not in config.allowed_api_paths:
        raise MesAccessError('MES_INTERFACE_DENIED', 403)
    filters = {} if filters is None else filters
    if (type(filters) is not dict or set(filters) - set(spec.filters)
            or type(page) is not int or not 1 <= page <= 1_000_000
            or spec.pagination_mode == 'bounded_data' and page != 1
            or type(page_size) is not int or not 1 <= page_size <= min(5, config.max_rows)):
        raise MesAccessError('MES_INVALID_QUERY', 400)
    payload = dict.fromkeys(spec.filters, '')
    for key, value in filters.items():
        if type(value) is not str or len(value) > 128:
            raise MesAccessError('MES_INVALID_QUERY', 400)
        if value:
            if key in DATE_KEYS:
                try:
                    if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
                        raise ValueError()
                    date.fromisoformat(value)
                except ValueError:
                    raise MesAccessError('MES_INVALID_QUERY', 400) from None
            elif not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:/ -]{0,127}', value):
                raise MesAccessError('MES_INVALID_QUERY', 400)
        payload[key] = value
    if any(not payload[key] for key in spec.required_filters):
        raise MesAccessError('MES_INVALID_QUERY', 400)
    for begin, end in [('startDate', 'endDate'), ('begindate', 'enddate'), ('date_start', 'date_end')]:
        if payload.get(begin) and payload.get(end) and payload[begin] > payload[end]:
            raise MesAccessError('MES_INVALID_QUERY', 400)
    payload.update(spec.fixed_fields)
    if spec.pagination_mode == 'bounded_data':
        # The template and every identifier are code-owned. The only insertion
        # is the exact integer already bounded above, never a caller SQL string.
        payload['querySql'] = payload['querySql'].format(row_limit=page_size)
    else:
        payload.update(pageNumber=page, **{spec.size_key: page_size})
    return spec, payload
