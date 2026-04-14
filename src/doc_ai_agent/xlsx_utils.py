"""轻量 XLSX 读取工具（基于 OpenXML 结构解析）。

不依赖 pandas/openpyxl，直接读取 zip 包内 XML，适合服务端批处理场景。
"""

from __future__ import annotations

import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Dict, Iterable, Iterator, List, Optional

NS_MAIN = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass(frozen=True)
class XlsxRow:
    """统一的行对象：包含工作表名、行号和“表头->值”映射。"""

    sheet_name: str
    row_index: int
    values: Dict[str, Optional[str]]


def _col_to_idx(cell_ref: str) -> int:
    """把 Excel 列引用（如 A、AB）转换成从 0 开始的列下标。"""
    col = re.match(r"[A-Z]+", cell_ref).group(0)
    idx = 0
    for c in col:
        idx = idx * 26 + (ord(c) - ord("A") + 1)
    return idx - 1


def _read_shared_strings(book: zipfile.ZipFile) -> List[str]:
    """读取共享字符串表（sharedStrings.xml）。"""
    if "xl/sharedStrings.xml" not in book.namelist():
        return []
    root = ET.fromstring(book.read("xl/sharedStrings.xml"))
    strings = []
    for si in root.findall("x:si", NS_MAIN):
        parts = []
        for node in si.iterfind(".//x:t", NS_MAIN):
            parts.append(node.text or "")
        strings.append("".join(parts))
    return strings


def _sheet_targets(book: zipfile.ZipFile) -> Dict[str, str]:
    """解析工作簿，得到“工作表名 -> 对应 XML 路径”。"""
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


def _extract_cells(row_elem: ET.Element, shared: List[str]) -> Dict[int, Optional[str]]:
    """提取单行单元格值，返回“列下标 -> 单元格值”。"""
    values: Dict[int, Optional[str]] = {}
    for cell in row_elem.findall("x:c", NS_MAIN):
        ref = cell.attrib.get("r", "A1")
        idx = _col_to_idx(ref)
        value_node = cell.find("x:v", NS_MAIN)
        if value_node is None or value_node.text is None:
            inline = cell.find("x:is", NS_MAIN)
            if inline is not None:
                # 兼容 inlineStr 单元格（文本直接嵌在单元格节点内）。
                text = "".join((t.text or "") for t in inline.iterfind(".//x:t", NS_MAIN))
                values[idx] = text
            else:
                values[idx] = None
            continue
        raw = value_node.text
        if cell.attrib.get("t") == "s":
            s_idx = int(raw)
            values[idx] = shared[s_idx] if 0 <= s_idx < len(shared) else None
        else:
            values[idx] = raw
    return values


def iter_xlsx_rows(path: str) -> Iterator[XlsxRow]:
    """按工作表顺序迭代数据行（首行默认作为表头）。"""
    with zipfile.ZipFile(path) as book:
        shared = _read_shared_strings(book)
        sheets = _sheet_targets(book)
        for sheet_name, target in sheets.items():
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            sheet_root = ET.fromstring(book.read(target))
            sheet_rows = sheet_root.findall("x:sheetData/x:row", NS_MAIN)
            if not sheet_rows:
                continue

            header_cells = _extract_cells(sheet_rows[0], shared)
            max_header = max(header_cells.keys()) if header_cells else -1
            ordered_headers = [header_cells.get(i, "") or "" for i in range(max_header + 1)]

            for row_elem in sheet_rows[1:]:
                cell_values = _extract_cells(row_elem, shared)
                payload = {}
                width = max(len(ordered_headers), (max(cell_values.keys()) + 1) if cell_values else 0)
                for idx in range(width):
                    # 对缺失表头的列自动生成 col_N，避免数据错位丢失。
                    header = ordered_headers[idx] if idx < len(ordered_headers) else f"col_{idx+1}"
                    payload[header or f"col_{idx+1}"] = cell_values.get(idx)
                yield XlsxRow(
                    sheet_name=sheet_name,
                    row_index=int(row_elem.attrib.get("r", "0") or 0),
                    values=payload,
                )


def read_xlsx_rows(path: str) -> List[XlsxRow]:
    """一次性读出全部行（在需要随机访问时使用）。"""
    return list(iter_xlsx_rows(path))
