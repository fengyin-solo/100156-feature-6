"""观测传感器业务规则：状态流转、字段校验、检定到期分类与筛选口径都收在这里。"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.store import store

MODULE = "sensor"
REQUIRED_FIELDS = ["传感器编号", "所属站点", "观测要素"]
# 登记时需要参与日期校验的字段：检定有效期不得早于安装日期
DATE_FIELDS = ["安装日期", "检定有效期"]
STATUS_ORDER = ["待检定", "正常采集", "疑误待查", "已拆除"]
REMOVED_STATUS = "已拆除"
ACTION_RULES = {"安排检定": "待检定", "标记疑误": "疑误待查", "拆除传感器": "已拆除"}
NEGATIVE_ACTIONS = []

# 到期分档：已过期 / 30 天内到期 / 正常（不含已拆除传感器）
EXPIRED = "已过期"
EXPIRING = "30天内到期"
NORMAL = "正常"
EXPIRY_BUCKETS = [EXPIRED, EXPIRING, NORMAL]
EXPIRING_SOON_DAYS = 30

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_iso_date(value: Any) -> date | None:
    """严格解析 YYYY-MM-DD：2026-02-30 这类不存在的日期返回 None，不做静默顺延。"""
    if not isinstance(value, str):
        return None
    match = _DATE_RE.match(value.strip())
    if match is None:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def is_removed(row: dict[str, Any]) -> bool:
    """已拆除的传感器不参与到期统计与到期分档。"""
    return row.get("status") == REMOVED_STATUS or str(row.get("传感器状态") or "").strip() == REMOVED_STATUS


def expiry_bucket(days_left: int | None) -> str | None:
    """按剩余天数分档；没有可解析检定有效期的记录不归属任何一档。"""
    if days_left is None:
        return None
    if days_left < 0:
        return EXPIRED
    if days_left <= EXPIRING_SOON_DAYS:
        return EXPIRING
    return NORMAL


class SensorService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        element: str | None = None,
        expiry: str | None = None,
        sort: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, dict[str, int]]:
        rows = store.rows(MODULE)
        today = date.today()
        decorated = [self._decorate(row, today) for row in rows]

        if keyword:
            decorated = [row for row in decorated if keyword in str(row.get("传感器编号", ""))]
        if element:
            decorated = [row for row in decorated if element in str(row.get("观测要素", ""))]
        if expiry:
            decorated = [row for row in decorated if row.get("expiryBucket") == expiry]

        if sort in ("expiry_asc", "expiry_desc"):
            reverse = sort == "expiry_desc"
            # 检定有效期缺失或无法解析的记录统一沉底，正序倒序都不夹在有效日期中间
            decorated.sort(
                key=lambda row: (
                    row["_expiry_date"] is None,
                    row["_expiry_date"] or date.min,
                ),
                reverse=reverse,
            )
            # reverse=True 会把“无日期”排到最前，需要单独把沉底组挪回末尾
            if reverse:
                valid = [row for row in decorated if row["_expiry_date"] is not None]
                missing = [row for row in decorated if row["_expiry_date"] is None]
                decorated = valid + missing

        total = len(decorated)
        start = max(page - 1, 0) * size
        page_rows = [self._public(row) for row in decorated[start:start + size]]
        return page_rows, total, self.summary()

    def summary(self) -> dict[str, int]:
        """全量到期统计（忽略当前查询条件），已拆除传感器不计入到期三档。

        页脚与统计卡片都读这份数据，保证两处口径一致；前端拿到什么就显示什么。
        """
        today = date.today()
        counts = {EXPIRED: 0, EXPIRING: 0, NORMAL: 0, "在装传感器": 0, "已拆除": 0}
        for row in store.rows(MODULE):
            if is_removed(row):
                counts["已拆除"] += 1
                continue
            counts["在装传感器"] += 1
            bucket = expiry_bucket(self._days_left(row, today))
            if bucket is not None:
                counts[bucket] += 1
        return counts

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        parsed_dates: dict[str, date] = {}
        invalid_dates: list[str] = []
        for field in DATE_FIELDS:
            raw = str(values.get(field) or "").strip()
            if not raw:
                invalid_dates.append(f"{field}不能为空，请填写 YYYY-MM-DD 格式的日期")
                continue
            parsed = parse_iso_date(raw)
            if parsed is None:
                invalid_dates.append(f"{field}「{raw}」不是有效日期（正确格式如 2026-09-27，且月份、日期要真实存在）")
            else:
                parsed_dates[field] = parsed
        if invalid_dates:
            return None, "；".join(invalid_dates)

        install_date = parsed_dates["安装日期"]
        expiry_date = parsed_dates["检定有效期"]
        if expiry_date < install_date:
            return None, f"检定有效期「{expiry_date.isoformat()}」不能早于安装日期「{install_date.isoformat()}」，请核对后重新填写"

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 其余可选字段原样登记，安装日期与检定有效期统一存成 YYYY-MM-DD
        for field in DATE_FIELDS:
            entry[field] = parsed_dates[field].isoformat()
        for field in ["设备型号", "出厂序列号", "安装高度"]:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["传感器状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, ""

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"观测传感器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于观测传感器可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["传感器状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"观测传感器已{action}"

    # ---- 内部工具 ----

    def _days_left(self, row: dict[str, Any], today: date) -> int | None:
        expiry_date = parse_iso_date(row.get("检定有效期"))
        if expiry_date is None:
            return None
        return (expiry_date - today).days

    def _decorate(self, row: dict[str, Any], today: date) -> dict[str, Any]:
        """浅拷贝后附加到期分档与剩余天数，避免把内部字段写回内存仓库。"""
        decorated = dict(row)
        if is_removed(row):
            decorated["_expiry_date"] = None
            decorated["expiryBucket"] = None
            decorated["daysLeft"] = None
            return decorated
        expiry_date = parse_iso_date(row.get("检定有效期"))
        days_left = (expiry_date - today).days if expiry_date is not None else None
        decorated["_expiry_date"] = expiry_date
        decorated["daysLeft"] = days_left
        decorated["expiryBucket"] = expiry_bucket(days_left)
        return decorated

    def _public(self, row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if not key.startswith("_")}
