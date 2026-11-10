"""Authorized read-only analytics without creating observation snapshots."""
from fastapi import Request
from pydantic import ValidationError

from .api import BASE, PREFIX, SourceId
from .contracts import AnalyticsFilters, AnalysisView
from .queries import PRODUCTION_FIELDS
from .source import error
from typing import get_args


def _parse(request, *, overview=False):
    allowed={'start','end','before_id'} if overview else {'start','end','view',*PRODUCTION_FIELDS}
    if set(request.query_params)-allowed or any(len(request.query_params.getlist(k))!=1 for k in request.query_params):
        raise error('SOURCE_INVALID_QUERY',422)
    values=dict(request.query_params)
    view=values.pop('view',None)
    before_id=values.pop('before_id',None)
    if not overview and view not in get_args(AnalysisView):
        raise error('SOURCE_INVALID_QUERY',422)
    try:
        return AnalyticsFilters(**values),view,before_id
    except (ValidationError,ValueError):
        raise error('SOURCE_INVALID_QUERY',422) from None


def register_analytics_routes(router,service,actor):
    @router.get(BASE+'/overview')
    def overview(request: Request):
        filters,_,before_id=_parse(request,overview=True)
        return service.overview(actor(request),filters,before_id=before_id)

    @router.get(PREFIX+'/analysis')
    def analysis(source_project_id: SourceId,request: Request):
        filters,view,_=_parse(request)
        return service.analysis(actor(request),source_project_id,filters,view)

    @router.get(PREFIX+'/availability')
    def availability(source_project_id: SourceId,request: Request):
        if request.query_params:
            raise error('SOURCE_INVALID_QUERY',422)
        return service.availability(actor(request),source_project_id)
