from enum import Enum
from pathlib import Path
from typing import Any, List, Optional

import wcmatch
import wcmatch.fnmatch
import wcmatch.glob
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from syftbox.client.exceptions import SyftPluginException
from syftbox.client.plugins.sync.local_state import SyncStatusInfo
from syftbox.client.plugins.sync.manager import SyncManager
from syftbox.client.plugins.sync.types import SyncStatus
from syftbox.client.routers.common import APIContext

router = APIRouter()
jinja_env = Environment(loader=FileSystemLoader("syftbox/assets/templates"))


def get_sync_manager(context: APIContext) -> SyncManager:
    try:
        return context.plugins.sync_manager
    except SyftPluginException as e:
        raise HTTPException(status_code=500, detail=f"Failed to get sync manager: {e}")


def _get_queued_items(sync_manager: SyncManager) -> List[SyncStatusInfo]:
    # make copy to avoid changing size during iteration
    queued_items = list(sync_manager.queue.all_items.values())
    return [
        SyncStatusInfo(
            path=item.data.path,
            status=SyncStatus.QUEUED,
            timestamp=item.enqueued_at,
        )
        for item in queued_items
    ]


def _get_items_from_localstate(sync_manager: SyncManager) -> List[SyncStatusInfo]:
    return list(sync_manager.local_state.status_info.values())


def _get_all_status_info(sync_manager: SyncManager) -> List[SyncStatusInfo]:
    """
    Return all status info from both the queue and local state.
    NOTE: the result might contain duplicates if the same path is present in both.
    """
    queued_items = _get_queued_items(sync_manager)
    localstate_items = _get_items_from_localstate(sync_manager)
    return queued_items + localstate_items


def _deduplicate_status_info(status_info_list: List[SyncStatusInfo]) -> List[SyncStatusInfo]:
    """Deduplicate status info by path, keeping the entry with latest timestamp"""
    path_to_info = {}
    for info in status_info_list:
        existing_info = path_to_info.get(info.path)
        if not existing_info or info.timestamp > existing_info.timestamp:
            path_to_info[info.path] = info
    return list(path_to_info.values())


def _sort_status_info(status_info_list: List[SyncStatusInfo], order_by: str, order: str) -> List[SyncStatusInfo]:
    if order_by.lower() not in SyncStatusInfo.model_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order_by field: {order_by}. Available fields: {list(SyncStatusInfo.model_fields.keys())}",
        )
    if order.lower() not in ["asc", "desc"]:
        raise HTTPException(status_code=400, detail=f"Invalid order: {order}, expected 'asc' or 'desc'")

    return list(
        sorted(
            status_info_list,
            key=lambda x: getattr(x, order_by),
            reverse=order.lower() == "desc",
        )
    )


class FilterOperator(str, Enum):
    eq = "eq"
    ne = "ne"
    lt = "lt"
    gt = "gt"
    le = "le"
    ge = "ge"
    glob = "glob"


def _evaluate_glob(value: Any, pattern: str) -> bool:
    # NOTE using fnmatch instead of glob to support basic patterns like "*.txt"
    if not isinstance(value, (Path, str)):
        return False
    return wcmatch.fnmatch.fnmatch(
        value.as_posix(),
        pattern,
    )


class FilterCondition(BaseModel):
    field: str
    op: FilterOperator
    value: Any

    def evaluate(self, item: Any) -> bool:
        """Return True if the item's field value satisfies the condition, False otherwise"""
        try:
            value = getattr(item, self.field)
            if self.op == FilterOperator.eq:
                return value == self.value
            elif self.op == FilterOperator.ne:
                return value != self.value
            elif self.op == FilterOperator.lt:
                return value < self.value
            elif self.op == FilterOperator.gt:
                return value > self.value
            elif self.op == FilterOperator.le:
                return value <= self.value
            elif self.op == FilterOperator.ge:
                return value >= self.value
            elif self.op == FilterOperator.glob:
                return _evaluate_glob(value, self.value)
            else:
                return False
        except Exception:
            # Failing comparisons always return False
            return False


def _apply_filter(status_info_list: List[SyncStatusInfo], condition: FilterCondition) -> List[SyncStatusInfo]:
    if condition.field not in SyncStatusInfo.model_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid filter field: {condition.field}. Available fields: {list(SyncStatusInfo.model_fields.keys())}",
        )
    return [item for item in status_info_list if condition.evaluate(item)]


def _filter_status_info(items: List[SyncStatusInfo], filters: Optional[List[FilterCondition]]) -> List[SyncStatusInfo]:
    if not filters:
        return items

    result = items
    for condition in filters:
        result = _apply_filter(result, condition)
    return result


class ListStatusInfoRequest(BaseModel):
    order_by: str = "timestamp"
    order: str = "desc"
    filters: Optional[List[FilterCondition]] = None


@router.post("/list_status_info")
def get_status_info(
    request: ListStatusInfoRequest,
    sync_manager: SyncManager = Depends(get_sync_manager),
) -> List[SyncStatusInfo]:
    all_items = _get_all_status_info(sync_manager)
    items_deduplicated = _deduplicate_status_info(all_items)
    items_filtered = _filter_status_info(items_deduplicated, request.filters)
    items_sorted = _sort_status_info(items_filtered, request.order_by, request.order)
    return items_sorted


@router.get("/")
def sync_dashboard(context: APIContext):
    template = jinja_env.get_template("sync_dashboard.jinja2")
    return HTMLResponse(template.render(base_url=context.config.client_url))
