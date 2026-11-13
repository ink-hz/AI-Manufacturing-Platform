"""Execution policy is independent of reachability and generated metadata."""

INTERFACES = {
    'RFC_PING': {'business': '连接与鉴权诊断', 'execution_enabled': True, 'blocking_reasons': []},
    'BAPI_PRODORD_GET_DETAIL': {'business': 'Single production order and components', 'execution_enabled': True, 'blocking_reasons': []},
    'BAPI_MATERIAL_STOCK_REQ_LIST': {'business': 'Stock and requirements list', 'execution_enabled': True, 'blocking_reasons': []},
    'ZMMRFC35': {'business': '采购订单及历史', 'execution_enabled': False,
        'blocking_reasons': ['NO_SOURCE_PAGINATION', 'UNGUARDED_EMPTY_FAE', 'GLOBAL_ENRICHMENT_READS', 'AMOUNT_SEMANTICS_UNVERIFIED']},
    'ZMMRFC78': {'business': '普通库存与项目库存', 'execution_enabled': False,
        'blocking_reasons': ['NO_SOURCE_PAGINATION', 'GLOBAL_PROJECT_READ', 'BATCH_MAPPING_UNVERIFIED']},
    'ZPPRFC06': {'business': '生产工单与组件', 'execution_enabled': False,
        'blocking_reasons': ['NO_SOURCE_PAGINATION', 'UNGUARDED_EMPTY_FAE', 'BUSINESS_SAMPLE_REQUIRED']},
    'ZMMRFC80': {'business': '物料凭证查询候选（历史资料）', 'execution_enabled': False,
        'blocking_reasons': ['VALID_WSDL_NOT_VERIFIED', 'ACTIVE_SOURCE_NOT_REVIEWED']},
}
