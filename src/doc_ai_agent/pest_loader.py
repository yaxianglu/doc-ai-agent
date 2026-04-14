"""虫情 Excel 加载与标准化模块。

主要负责把原始字段转成事实表可直接入库的结构，并附带基础数据质量标记。
"""

from __future__ import annotations

import datetime as dt
import os
import re
from typing import Dict, Iterable, Iterator, List, Optional

from .xlsx_utils import iter_xlsx_rows


def excel_serial_to_datetime(serial_text: Optional[str]) -> Optional[str]:
    """将 Excel 序列时间或原始文本统一为时间字符串。"""
    if serial_text in (None, ""):
        return None
    try:
        serial = float(serial_text)
    except (TypeError, ValueError):
        return str(serial_text)
    epoch = dt.datetime(1899, 12, 30)
    value = epoch + dt.timedelta(days=serial)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def split_csv_text(value: Optional[str]) -> List[str]:
    """把逗号分隔文本拆成去空格后的列表。"""
    if value in (None, ""):
        return []
    return [part.strip() for part in str(value).split(",") if part and part.strip()]


def normalize_pest_names(value: Optional[str]) -> tuple[Optional[str], bool]:
    """标准化虫种名称；全数字内容视为无效名称。"""
    parts = split_csv_text(value)
    if not parts:
        return None, False
    if all(re.fullmatch(r"[0-9.]+", part or "") for part in parts):
        return None, False
    return "|".join(parts), True


def normalize_pest_count(value: Optional[str]) -> tuple[Optional[float], str]:
    """标准化虫口数量，并返回数据质量状态码。"""
    parts = split_csv_text(value)
    if not parts:
        return None, "missing_pest_num"

    numbers: List[float] = []
    for part in parts:
        try:
            number = float(part)
        except ValueError:
            return None, "invalid_pest_num"
        if number < 0:
            return None, "negative_pest_num"
        if number > 10000:
            return None, "outlier_pest_num"
        numbers.append(number)

    if not numbers:
        return None, "missing_pest_num"
    return round(sum(numbers), 2), "ok"


def build_pest_row(raw: dict, source_file: str, source_sheet: str, source_row: int, batch_id: str) -> dict:
    """将单行原始数据转换为虫情事实表记录。"""
    normalized_names, names_usable = normalize_pest_names(raw.get("pest_name"))
    normalized_count, count_flag = normalize_pest_count(raw.get("pest_num"))
    severity_usable = 1 if normalized_count is not None else 0
    data_quality_flags = []
    if not names_usable:
        data_quality_flags.append("invalid_pest_name")
    if count_flag != "ok":
        data_quality_flags.append(count_flag)
    if raw.get("lon") in (None, "") or raw.get("lat") in (None, ""):
        data_quality_flags.append("missing_geo")

    return {
        "record_id": raw.get("id"),
        "batch_id": batch_id,
        "device_name": raw.get("device_name"),
        "device_type": raw.get("device_type"),
        "device_status": raw.get("device_status"),
        "device_sn": raw.get("sn"),
        "city_name": raw.get("city"),
        "county_name": raw.get("country"),
        "longitude": float(raw["lon"]) if raw.get("lon") not in (None, "") else None,
        "latitude": float(raw["lat"]) if raw.get("lat") not in (None, "") else None,
        "pest_name_raw": raw.get("pest_name"),
        "pest_num_raw": raw.get("pest_num"),
        "normalized_pest_names": normalized_names,
        "normalized_pest_count": normalized_count,
        "severity_usable": severity_usable,
        "data_quality_flag": "|".join(data_quality_flags) if data_quality_flags else "ok",
        "monitor_time": excel_serial_to_datetime(raw.get("monitor_time")),
        "create_time": excel_serial_to_datetime(raw.get("create_time")),
        "source_file": source_file,
        "source_sheet": source_sheet,
        "source_row": source_row,
    }


def iter_rows(path: str, batch_id: str) -> Iterator[dict]:
    """逐行产出可入库虫情记录。"""
    source_file = os.path.basename(path)
    for row in iter_xlsx_rows(path):
        payload = build_pest_row(row.values, source_file, row.sheet_name, row.row_index, batch_id)
        if not payload.get("record_id"):
            # 没有主键 ID 的记录无法安全去重，直接丢弃。
            continue
        yield payload
