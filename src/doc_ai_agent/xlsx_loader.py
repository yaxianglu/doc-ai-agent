"""历史告警 Excel 加载器。

这是一个向后兼容入口：用于解析“原始告警工作簿”并映射到统一告警字段。
"""

from __future__ import annotations

# Legacy loader kept for backward compatibility with the original alert workbook.

from typing import List

from .soil_loader import iter_device_mappings_from_alert_xlsx
from .xlsx_utils import iter_xlsx_rows
import datetime as dt
import os

HEADER_MAP = {
    "告警内容": "alert_content",
    "告警类型(预警信号,虫情,土壤)": "alert_type",
    "告警子类型": "alert_subtype",
    "告警时间": "alert_time",
    "告警等级": "alert_level",
    "区域编码": "region_code",
    "区域名称": "region_name",
    "告警值": "alert_value",
    "设备编码": "device_code",
    "设备名称": "device_name",
    "经度": "longitude",
    "维度": "latitude",
    "设备所在市": "city",
    "设备所在区县": "county",
    "短信内容": "sms_content",
    "处置建议": "disposal_suggestion",
}


def _excel_serial_to_datetime(serial_text: str) -> str:
    """把 Excel 序列日期转为标准时间字符串。"""
    try:
        serial = float(serial_text)
    except (TypeError, ValueError):
        return serial_text
    epoch = dt.datetime(1899, 12, 30)
    value = epoch + dt.timedelta(days=serial)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def load_alerts_from_xlsx(path: str) -> List[dict]:
    """读取告警 Excel，输出统一字段的告警列表。"""
    rows: List[dict] = []
    for row in iter_xlsx_rows(path):
        payload = {}
        for raw_header, value in row.values.items():
            if raw_header not in HEADER_MAP:
                continue
            key = HEADER_MAP[raw_header]
            if key == "alert_time" and value not in (None, ""):
                # Excel 中时间可能是数字序列值，需要显式转换。
                value = _excel_serial_to_datetime(value)
            payload[key] = value or ""
        if not payload.get("alert_content"):
            # 没有告警内容的行通常是空行或噪声行。
            continue
        payload["source_file"] = os.path.basename(path)
        payload["source_sheet"] = row.sheet_name
        payload["source_row"] = row.row_index
        rows.append(payload)
    return rows
