from __future__ import annotations

import datetime as dt
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Dict, List

NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
NS_REL = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

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


def _col_to_idx(cell_ref: str) -> int:
    col = re.match(r"[A-Z]+", cell_ref).group(0)
    idx = 0
    for c in col:
        idx = idx * 26 + (ord(c) - ord("A") + 1)
    return idx - 1


def _excel_serial_to_datetime(serial_text: str) -> str:
    try:
        serial = float(serial_text)
    except (TypeError, ValueError):
        return serial_text
    epoch = dt.datetime(1899, 12, 30)
    value = epoch + dt.timedelta(days=serial)
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _read_shared_strings(book: zipfile.ZipFile) -> List[str]:
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall("x:si", NS_MAIN):
        t = si.find("x:t", NS_MAIN)
        if t is not None:
            strings.append(t.text or "")
            continue
        # Rich text support.
        parts = []
        for run in si.findall("x:r", NS_MAIN):
            rt = run.find("x:t", NS_MAIN)
            if rt is not None and rt.text:
                parts.append(rt.text)
        strings.append("".join(parts))
    return strings


def _sheet_targets(book: zipfile.ZipFile) -> Dict[str, str]:
    workbook = ET.fromstring(book.read("xl/workbook.xml"))
    rels = ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))

    rel_map = {}
    for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        rel_map[rel.attrib["Id"]] = rel.attrib["Target"]

    targets = {}
    for sheet in workbook.findall("x:sheets/x:sheet", NS_MAIN):
        name = sheet.attrib.get("name", "")
        rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = rel_map.get(rid)
        if target:
            targets[name] = target.lstrip("/")
    return targets


def _extract_cells(row_elem: ET.Element, shared: List[str]) -> Dict[int, str]:
    values: Dict[int, str] = {}
    for cell in row_elem.findall("x:c", NS_MAIN):
        ref = cell.attrib.get("r", "A1")
        idx = _col_to_idx(ref)
        value_node = cell.find("x:v", NS_MAIN)
        if value_node is None or value_node.text is None:
            values[idx] = ""
            continue
        raw = value_node.text
        if cell.attrib.get("t") == "s":
            s_idx = int(raw)
            values[idx] = shared[s_idx] if 0 <= s_idx < len(shared) else ""
        else:
            values[idx] = raw
    return values


def load_alerts_from_xlsx(path: str) -> List[dict]:
    with zipfile.ZipFile(path) as book:
        shared = _read_shared_strings(book)
        sheets = _sheet_targets(book)

        rows: List[dict] = []
        for sheet_name, target in sheets.items():
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            sheet_root = ET.fromstring(book.read(target))
            sheet_rows = sheet_root.findall("x:sheetData/x:row", NS_MAIN)
            if not sheet_rows:
                continue

            header_cells = _extract_cells(sheet_rows[0], shared)
            ordered_headers = [header_cells.get(i, "") for i in range(max(header_cells.keys()) + 1)]

            for row_elem in sheet_rows[1:]:
                cell_values = _extract_cells(row_elem, shared)
                payload = {}
                for idx, header in enumerate(ordered_headers):
                    if header not in HEADER_MAP:
                        continue
                    key = HEADER_MAP[header]
                    value = cell_values.get(idx, "")
                    if key == "alert_time":
                        value = _excel_serial_to_datetime(value)
                    payload[key] = value

                if not payload.get("alert_content"):
                    continue

                payload["source_file"] = os.path.basename(path)
                payload["source_sheet"] = sheet_name
                payload["source_row"] = int(row_elem.attrib.get("r", "0"))
                rows.append(payload)

    return rows
