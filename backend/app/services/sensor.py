"""观测传感器业务规则：检定有效期分级、状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "sensor"
REQUIRED_FIELDS = ["传感器编号", "所属站点", "观测要素"]
STATUS_ORDER = ["待检定", "正常采集", "疑误待查", "已拆除"]
ACTION_RULES = {"安排检定": "待检定", "标记疑误": "疑误待查", "拆除传感器": "已拆除"}
NEGATIVE_ACTIONS = []

REMOVED_STATUS = "已拆除"
EXPIRY_SOON_DAYS = 30
EXPIRY_BUCKETS = ["已过期", "30天内到期", "正常"]
EXPIRY_SORTS = {"asc", "desc"}


def parse_date(value: Any) -> date | None:
    """把 YYYY-MM-DD（兼容 YYYY/M/D）解析成日期；不存在的月份或日期返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    parts = text.replace("/", "-").split("-")
    if len(parts) != 3:
        return None
    try:
        year, month, day = (int(part) for part in parts)
        return date(year, month, day)
    except ValueError:
        return None


def expiry_info(row: dict[str, Any], today: date) -> dict[str, Any]:
    """按检定有效期与当前日期把记录分成已过期、30天内到期、正常；已拆除不参与分级。"""
    if row.get("status") == REMOVED_STATUS:
        return {"到期情况": None, "剩余天数": None}
    due = parse_date(row.get("检定有效期"))
    if due is None:
        return {"到期情况": None, "剩余天数": None}
    days = (due - today).days
    if days < 0:
        bucket = "已过期"
    elif days <= EXPIRY_SOON_DAYS:
        bucket = "30天内到期"
    else:
        bucket = "正常"
    return {"到期情况": bucket, "剩余天数": days}


class SensorService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        element: str | None = None,
        status: str | None = None,
        expiry: str | None = None,
        sort: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        today = date.today()
        rows = []
        for row in store.rows(MODULE):
            item = dict(row)
            item.update(expiry_info(row, today))
            rows.append(item)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("传感器编号", ""))]
        if element:
            rows = [row for row in rows if element in str(row.get("观测要素", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if expiry:
            rows = [row for row in rows if row.get("到期情况") == expiry]
        if sort in EXPIRY_SORTS:
            rows = sorted(rows, key=lambda row: self._expiry_sort_key(row, sort))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    @staticmethod
    def _expiry_sort_key(row: dict[str, Any], sort: str) -> tuple[int, int]:
        """按剩余天数排序；无法分级的记录（已拆除、有效期缺失）始终排在最后。"""
        days = row.get("剩余天数")
        if days is None:
            return (1, 0)
        return (0, -int(days) if sort == "desc" else int(days))

    def expiry_stats(self) -> dict[str, int]:
        """统计三种到期情况的条数；已拆除的传感器不参与统计。"""
        today = date.today()
        stats = {bucket: 0 for bucket in EXPIRY_BUCKETS}
        for row in store.rows(MODULE):
            if row.get("status") == REMOVED_STATUS:
                continue
            bucket = expiry_info(row, today)["到期情况"]
            if bucket in stats:
                stats[bucket] += 1
        return stats

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"观测传感器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于观测传感器可执行范围"
        values = values or {}
        if action == "安排检定":
            message = self._apply_calibration_date(entry, values)
            if message is not None:
                return None, message
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["传感器状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"观测传感器已{action}"

    @staticmethod
    def _apply_calibration_date(entry: dict[str, Any], values: dict[str, Any]) -> str | None:
        """安排检定时先拦下问题日期：不存在的日期、早于安装日期，都说明哪一项有问题。"""
        raw_due = str(values.get("检定有效期") or "").strip()
        if not raw_due:
            return "请先填写检定有效期再安排检定"
        due = parse_date(raw_due)
        if due is None:
            return f"检定有效期「{raw_due}」不是有效日期，请检查月份或日期是否存在"
        installed = parse_date(entry.get("安装日期"))
        if installed is not None and due < installed:
            return f"检定有效期 {due.isoformat()} 早于安装日期 {installed.isoformat()}，请核对后再提交"
        entry["检定有效期"] = due.isoformat()
        return None
