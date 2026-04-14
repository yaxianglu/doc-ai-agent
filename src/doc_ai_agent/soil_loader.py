"""墒情 Excel 加载与标准化模块。

负责把原始墒情行数据转换为事实表结构，并给出基础异常分类与质量标记。
"""

from __future__ import annotations

import datetime as dt
import os
from typing import Dict, Iterator, Optional

from .xlsx_utils import iter_xlsx_rows


def excel_serial_to_datetime(serial_text: Optional[str]) -> Optional[str]:
    """将 Excel 序列时间转换为标准时间字符串。"""
    if serial_text in (None, ""):
        return None
    try:
        serial = float(serial_text)
    except (TypeError, ValueError):
        return str(serial_text)
    epoch = dt.datetime(1899, 12, 30)
    value = epoch + dt.timedelta(days=serial)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def to_float(value: Optional[str]) -> Optional[float]:
    """尽力把输入转成浮点数；失败时返回 `None`。"""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_soil_anomaly(water20cm: Optional[float]) -> tuple[str, float]:
    """按 20cm 含水量阈值判断墒情异常类型与评分。"""
    if water20cm is None:
        return "unknown", 0.0
    if water20cm < 50:
        return "low", round(50 - water20cm, 2)
    if water20cm > 150:
        return "high", round(water20cm - 150, 2)
    return "normal", 0.0


def data_quality_flag(water20cm: Optional[float], t20cm: Optional[float]) -> str:
    """生成墒情记录质量标记。"""
    flags = []
    if water20cm is None:
        flags.append("missing_water20cm")
    elif not (0 <= water20cm <= 300):
        flags.append("invalid_water20cm")
    if t20cm is None:
        flags.append("missing_t20cm")
    elif not (-30 <= t20cm <= 60):
        flags.append("invalid_t20cm")
    return "|".join(flags) if flags else "ok"


def build_soil_row(raw: dict, source_file: str, source_sheet: str, source_row: int, batch_id: str) -> dict:
    """将单行原始数据转换为墒情事实表记录。"""
    water20cm = to_float(raw.get("water20cm"))
    t20cm = to_float(raw.get("t20cm"))
    anomaly_type, anomaly_score = classify_soil_anomaly(water20cm)
    quality_flag = data_quality_flag(water20cm, t20cm)
    water20cm_valid = 1 if water20cm is not None and 0 <= water20cm <= 300 else 0
    t20cm_valid = 1 if t20cm is not None and -30 <= t20cm <= 60 else 0

    return {
        "record_id": raw.get("id"),
        "batch_id": batch_id,
        "device_sn": raw.get("sn"),
        "gateway_id": raw.get("gatewayid"),
        "sensor_id": raw.get("sensorid"),
        "unit_id": raw.get("unitid"),
        "sample_time": excel_serial_to_datetime(raw.get("time")),
        "water20cm": water20cm,
        "water40cm": to_float(raw.get("water40cm")),
        "water60cm": to_float(raw.get("water60cm")),
        "water80cm": to_float(raw.get("water80cm")),
        "t20cm": t20cm,
        "t40cm": to_float(raw.get("t40cm")),
        "t60cm": to_float(raw.get("t60cm")),
        "t80cm": to_float(raw.get("t80cm")),
        "water20cm_field_state": raw.get("water20cmfieldstate"),
        "water40cm_field_state": raw.get("water40cmfieldstate"),
        "water60cm_field_state": raw.get("water60cmfieldstate"),
        "water80cm_field_state": raw.get("water80cmfieldstate"),
        "t20cm_field_state": raw.get("t20cmfieldstate"),
        "t40cm_field_state": raw.get("t40cmfieldstate"),
        "t60cm_field_state": raw.get("t60cmfieldstate"),
        "t80cm_field_state": raw.get("t80cmfieldstate"),
        "water20cm_valid": water20cm_valid,
        "t20cm_valid": t20cm_valid,
        "soil_anomaly_type": anomaly_type,
        "soil_anomaly_score": anomaly_score,
        "data_quality_flag": quality_flag,
        "create_time": excel_serial_to_datetime(raw.get("create_time")),
        "source_file": source_file,
        "source_sheet": source_sheet,
        "source_row": source_row,
    }


def iter_rows(path: str, batch_id: str) -> Iterator[dict]:
    """逐行产出可入库墒情记录。"""
    source_file = os.path.basename(path)
    for row in iter_xlsx_rows(path):
        payload = build_soil_row(row.values, source_file, row.sheet_name, row.row_index, batch_id)
        if not payload.get("record_id"):
            continue
        yield payload


def iter_device_mappings_from_alert_xlsx(path: str) -> Iterator[dict]:
    """从历史告警表中提取墒情设备映射信息。"""
    for row in iter_xlsx_rows(path):
        values = row.values
        if values.get("告警类型(预警信号,虫情,土壤)") != "土壤墒情仪":
            continue
        device_sn = values.get("设备编码")
        if not device_sn:
            continue
        yield {
            "device_sn": device_sn,
            "device_name": values.get("设备名称"),
            "device_type": values.get("告警类型(预警信号,虫情,土壤)"),
            "city_name": values.get("设备所在市"),
            "county_name": values.get("设备所在区县"),
            "town_name": values.get("区域名称"),
            "longitude": to_float(values.get("经度")),
            "latitude": to_float(values.get("维度")),
            "mapping_source": os.path.basename(path),
            "mapping_confidence": "alert_enrichment",
        }
