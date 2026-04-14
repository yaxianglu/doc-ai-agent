"""SQLite 告警仓储模块。

该模块提供轻量数据访问能力，主要用于：
- 初始化本地告警表结构
- 批量写入去重后的告警数据
- 提供常见统计与趋势查询
"""

from __future__ import annotations

import os
import sqlite3
from typing import Iterable, List, Optional


class AlertRepository:
    """告警数据仓储（SQLite 实现）。"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        """创建数据库连接，并使用按列名访问的行对象。"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """初始化告警表与唯一约束。"""
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_content TEXT,
                    alert_type TEXT,
                    alert_subtype TEXT,
                    alert_time TEXT,
                    alert_level TEXT,
                    region_code TEXT,
                    region_name TEXT,
                    alert_value TEXT,
                    device_code TEXT,
                    device_name TEXT,
                    longitude TEXT,
                    latitude TEXT,
                    city TEXT,
                    county TEXT,
                    sms_content TEXT,
                    disposal_suggestion TEXT,
                    source_file TEXT,
                    source_sheet TEXT,
                    source_row INTEGER,
                    UNIQUE(source_file, source_sheet, source_row)
                )
                """
            )

    def insert_alerts(self, rows: Iterable[dict]) -> int:
        """批量写入告警，按来源文件+sheet+行号做幂等替换。"""
        sql = """
            INSERT OR REPLACE INTO alerts (
                alert_content, alert_type, alert_subtype, alert_time, alert_level,
                region_code, region_name, alert_value, device_code, device_name,
                longitude, latitude, city, county, sms_content, disposal_suggestion,
                source_file, source_sheet, source_row
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        payload = [
            (
                row.get("alert_content", ""),
                row.get("alert_type", ""),
                row.get("alert_subtype", ""),
                row.get("alert_time", ""),
                row.get("alert_level", ""),
                row.get("region_code", ""),
                row.get("region_name", ""),
                row.get("alert_value", ""),
                row.get("device_code", ""),
                row.get("device_name", ""),
                row.get("longitude", ""),
                row.get("latitude", ""),
                row.get("city", ""),
                row.get("county", ""),
                row.get("sms_content", ""),
                row.get("disposal_suggestion", ""),
                row.get("source_file", ""),
                row.get("source_sheet", ""),
                int(row.get("source_row", 0)),
            )
            for row in rows
        ]
        with self._connect() as conn:
            conn.executemany(sql, payload)
            return len(payload)

    def count_since(self, since: str) -> int:
        """统计指定时间（含）之后的告警总数。"""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE alert_time >= ?", (since,)
            )
            return int(cur.fetchone()["c"])

    def top_n(self, field: str, n: int, since: str) -> List[dict]:
        """按字段聚合 Top N（仅允许白名单字段，防止 SQL 注入）。"""
        allowed = {"city", "county", "alert_type", "alert_level"}
        if field not in allowed:
            raise ValueError("unsupported field")
        sql = f"""
            SELECT {field} AS name, COUNT(*) AS cnt
            FROM alerts
            WHERE alert_time >= ?
            GROUP BY {field}
            ORDER BY cnt DESC, name ASC
            LIMIT ?
        """
        with self._connect() as conn:
            cur = conn.execute(sql, (since, n))
            return [{"name": r["name"], "count": int(r["cnt"])} for r in cur.fetchall()]

    def sample_alerts(self, since: str, limit: int = 3) -> List[dict]:
        """返回最近告警样本，便于提示词拼接或调试展示。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT alert_time, city, county, alert_type, alert_level, alert_content, source_file, source_sheet, source_row
                FROM alerts
                WHERE alert_time >= ?
                ORDER BY alert_time DESC
                LIMIT ?
                """,
                (since, limit),
            )
            rows = []
            for r in cur.fetchall():
                rows.append(
                    {
                        "alert_time": r["alert_time"],
                        "city": r["city"],
                        "county": r["county"],
                        "alert_type": r["alert_type"],
                        "alert_level": r["alert_level"],
                        "alert_content": r["alert_content"],
                        "source_file": r["source_file"],
                        "source_sheet": r["source_sheet"],
                        "source_row": int(r["source_row"] or 0),
                    }
                )
            return rows

    def available_alert_time_range(self) -> Optional[dict]:
        """返回库内可用告警时间范围；无数据则返回 `None`。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT MIN(alert_time) AS min_time, MAX(alert_time) AS max_time
                FROM alerts
                WHERE alert_time IS NOT NULL AND TRIM(alert_time) != ''
                """
            )
            row = cur.fetchone()
            if row is None or not row["min_time"] or not row["max_time"]:
                return None
            return {
                "min_time": row["min_time"],
                "max_time": row["max_time"],
            }

    def avg_alert_value_by_level(self, since: str) -> List[dict]:
        """按告警等级计算平均告警值。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT
                    alert_level AS level,
                    AVG(CAST(alert_value AS REAL)) AS avg_alert_value,
                    COUNT(*) AS cnt
                FROM alerts
                WHERE alert_time >= ? AND TRIM(alert_value) != ''
                GROUP BY alert_level
                ORDER BY avg_alert_value DESC, level ASC
                """,
                (since,),
            )
            rows = []
            for r in cur.fetchall():
                rows.append(
                    {
                        "level": r["level"],
                        "avg_alert_value": round(float(r["avg_alert_value"]), 2),
                        "count": int(r["cnt"]),
                    }
                )
            return rows

    def devices_triggered_on_multiple_days(self, since: str, min_days: int = 2, limit: int = 50) -> List[dict]:
        """查询跨多天反复触发告警的设备。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT
                    device_code,
                    MAX(device_name) AS device_name,
                    COUNT(DISTINCT SUBSTR(alert_time, 1, 10)) AS day_cnt,
                    MIN(SUBSTR(alert_time, 1, 10)) AS first_day,
                    MAX(SUBSTR(alert_time, 1, 10)) AS last_day
                FROM alerts
                WHERE alert_time >= ? AND TRIM(device_code) != ''
                GROUP BY device_code
                HAVING day_cnt >= ?
                ORDER BY day_cnt DESC, device_code ASC
                LIMIT ?
                """,
                (since, max(2, int(min_days)), max(1, int(limit))),
            )
            rows = []
            for r in cur.fetchall():
                rows.append(
                    {
                        "device_code": r["device_code"],
                        "device_name": r["device_name"],
                        "active_days": int(r["day_cnt"]),
                        "first_day": r["first_day"],
                        "last_day": r["last_day"],
                    }
                )
            return rows

    def count_filtered(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        level: Optional[str] = None,
    ) -> int:
        """按时间和可选维度过滤后统计告警条数。"""
        where = ["alert_time >= ?"]
        params: list = [since]
        if until:
            where.append("alert_time < ?")
            params.append(until)
        if city:
            where.append("city = ?")
            params.append(city)
        if level:
            where.append("alert_level = ?")
            params.append(level)
        sql = f"SELECT COUNT(*) AS c FROM alerts WHERE {' AND '.join(where)}"
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.fetchone()["c"])

    def alerts_trend(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
    ) -> List[dict]:
        """按天返回告警趋势。"""
        where = ["alert_time >= ?"]
        params: list[object] = [since]
        if until:
            where.append("alert_time < ?")
            params.append(until)
        if city:
            where.append("city = ?")
            params.append(city)
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                SELECT
                    SUBSTR(alert_time, 1, 10) AS date,
                    COUNT(*) AS alert_count
                FROM alerts
                WHERE {' AND '.join(where)}
                GROUP BY SUBSTR(alert_time, 1, 10)
                ORDER BY date ASC
                """,
                tuple(params),
            )
            return [
                {
                    "date": r["date"],
                    "alert_count": int(r["alert_count"]),
                }
                for r in cur.fetchall()
            ]

    def top_n_filtered(
        self,
        field: str,
        n: int,
        since: str,
        until: Optional[str] = None,
        min_alert_value: Optional[float] = None,
    ) -> List[dict]:
        """按字段做带阈值过滤的 TopN 统计。"""
        allowed = {"city", "county", "alert_type", "alert_level"}
        if field not in allowed:
            raise ValueError("unsupported field")
        where = ["alert_time >= ?"]
        params: list = [since]
        if until:
            where.append("alert_time < ?")
            params.append(until)
        if min_alert_value is not None:
            where.append("CAST(alert_value AS REAL) > ?")
            params.append(float(min_alert_value))
        sql = f"""
            SELECT {field} AS name, COUNT(*) AS cnt
            FROM alerts
            WHERE {' AND '.join(where)}
            GROUP BY {field}
            ORDER BY cnt DESC, name ASC
            LIMIT ?
        """
        params.append(n)
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return [{"name": r["name"], "count": int(r["cnt"])} for r in cur.fetchall()]

    def highest_alert_values(self, limit: int = 10, since: Optional[str] = None) -> List[dict]:
        """返回告警值最高的若干条记录。"""
        where = ["TRIM(alert_value) != ''"]
        params: list = []
        if since:
            where.append("alert_time >= ?")
            params.append(since)
        sql = f"""
            SELECT alert_time, device_code, device_name, city, county, alert_value
            FROM alerts
            WHERE {' AND '.join(where)}
            ORDER BY CAST(alert_value AS REAL) DESC, alert_time DESC
            LIMIT ?
        """
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            rows = []
            for r in cur.fetchall():
                rows.append(
                    {
                        "alert_time": r["alert_time"],
                        "device_code": r["device_code"],
                        "device_name": r["device_name"],
                        "city": r["city"],
                        "county": r["county"],
                        "alert_value": float(r["alert_value"]),
                    }
                )
            return rows

    def latest_by_device(self, device_code: str) -> Optional[dict]:
        """查询某设备最近一次告警记录。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT alert_time, alert_level, disposal_suggestion, city, county, device_code, device_name
                FROM alerts
                WHERE device_code = ?
                ORDER BY alert_time DESC
                LIMIT 1
                """,
                (device_code,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "alert_time": row["alert_time"],
                "alert_level": row["alert_level"],
                "disposal_suggestion": row["disposal_suggestion"],
                "city": row["city"],
                "county": row["county"],
                "device_code": row["device_code"],
                "device_name": row["device_name"],
            }

    def latest_by_region_keyword(self, city_or_county_keyword: str, region_keyword: str) -> Optional[dict]:
        """查询某地区下包含指定区域关键词的最近告警。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT alert_time, alert_level, disposal_suggestion, city, county, region_name, device_code
                FROM alerts
                WHERE (city = ? OR county = ?) AND region_name LIKE ?
                ORDER BY alert_time DESC
                LIMIT 1
                """,
                (city_or_county_keyword, city_or_county_keyword, f"%{region_keyword}%"),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "alert_time": row["alert_time"],
                "alert_level": row["alert_level"],
                "disposal_suggestion": row["disposal_suggestion"],
                "city": row["city"],
                "county": row["county"],
                "region_name": row["region_name"],
                "device_code": row["device_code"],
            }

    def sms_empty_records(self, county_keyword: str, limit: int = 20) -> List[dict]:
        """列出短信内容为空的记录，便于排查采集问题。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT alert_time, city, county, device_code, alert_level
                FROM alerts
                WHERE county = ? AND (sms_content IS NULL OR TRIM(sms_content) = '')
                ORDER BY alert_time DESC
                LIMIT ?
                """,
                (county_keyword, max(1, int(limit))),
            )
            rows = []
            for r in cur.fetchall():
                rows.append(
                    {
                        "alert_time": r["alert_time"],
                        "city": r["city"],
                        "county": r["county"],
                        "device_code": r["device_code"],
                        "alert_level": r["alert_level"],
                    }
                )
            return rows

    def top_active_devices(self, since: str, until: Optional[str] = None, limit: int = 10) -> List[dict]:
        """统计一段时间内最活跃的设备。"""
        where = ["alert_time >= ?", "device_code IS NOT NULL", "TRIM(device_code) != ''"]
        params: list[object] = [since]
        if until:
            where.append("alert_time < ?")
            params.append(until)
        params.append(max(1, int(limit)))
        with self._connect() as conn:
            cur = conn.execute(
                f"""
                SELECT
                    device_code,
                    device_name,
                    COUNT(*) AS alert_count,
                    COUNT(DISTINCT substr(alert_time, 1, 10)) AS active_days,
                    MAX(alert_time) AS last_alert_time
                FROM alerts
                WHERE {' AND '.join(where)}
                GROUP BY device_code, device_name
                ORDER BY alert_count DESC, active_days DESC, last_alert_time DESC, device_code ASC
                LIMIT ?
                """,
                tuple(params),
            )
            return [
                {
                    "device_code": r["device_code"],
                    "device_name": r["device_name"],
                    "alert_count": int(r["alert_count"]),
                    "active_days": int(r["active_days"]),
                    "last_alert_time": r["last_alert_time"],
                }
                for r in cur.fetchall()
            ]

    def unknown_region_devices(self, limit: int = 20) -> List[dict]:
        """找出落在未知地区或地区字段缺失的设备。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT
                    device_code,
                    device_name,
                    COUNT(*) AS alert_count,
                    MAX(alert_time) AS last_alert_time
                FROM alerts
                WHERE device_code IS NOT NULL
                  AND TRIM(device_code) != ''
                  AND (
                    city IS NULL OR TRIM(city) = ''
                    OR county IS NULL OR TRIM(county) = ''
                    OR county IN ('未知地区', '未知区域', '未知区')
                  )
                GROUP BY device_code, device_name
                ORDER BY alert_count DESC, last_alert_time DESC, device_code ASC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
            return [
                {
                    "device_code": r["device_code"],
                    "device_name": r["device_name"],
                    "alert_count": int(r["alert_count"]),
                    "last_alert_time": r["last_alert_time"],
                }
                for r in cur.fetchall()
            ]

    def empty_county_records(self, limit: int = 20) -> List[dict]:
        """列出县字段为空的原始告警记录。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT alert_time, city, county, region_name, device_code, device_name, alert_level
                FROM alerts
                WHERE county IS NULL OR TRIM(county) = ''
                ORDER BY alert_time DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
            return [
                {
                    "alert_time": r["alert_time"],
                    "city": r["city"],
                    "county": r["county"],
                    "region_name": r["region_name"],
                    "device_code": r["device_code"],
                    "device_name": r["device_name"],
                    "alert_level": r["alert_level"],
                }
                for r in cur.fetchall()
            ]

    def unmatched_region_records(self, limit: int = 20) -> List[dict]:
        """列出城市、县或区域名称缺失的未匹配记录。"""
        with self._connect() as conn:
            cur = conn.execute(
                """
                SELECT alert_time, city, county, region_name, device_code, device_name, alert_level
                FROM alerts
                WHERE
                    city IS NULL OR TRIM(city) = ''
                    OR county IS NULL OR TRIM(county) = ''
                    OR region_name IS NULL OR TRIM(region_name) = ''
                ORDER BY alert_time DESC
                LIMIT ?
                """,
                (max(1, int(limit)),),
            )
            return [
                {
                    "alert_time": r["alert_time"],
                    "city": r["city"],
                    "county": r["county"],
                    "region_name": r["region_name"],
                    "device_code": r["device_code"],
                    "device_name": r["device_name"],
                    "alert_level": r["alert_level"],
                }
                for r in cur.fetchall()
            ]

    def subtype_ratio(self, alert_type: str, alert_subtype: str, since: str) -> dict:
        """计算某子类型在指定告警类型中的占比。"""
        with self._connect() as conn:
            total_cur = conn.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE alert_time >= ? AND alert_type = ?",
                (since, alert_type),
            )
            total = int(total_cur.fetchone()["c"])
            sub_cur = conn.execute(
                "SELECT COUNT(*) AS c FROM alerts WHERE alert_time >= ? AND alert_type = ? AND alert_subtype = ?",
                (since, alert_type, alert_subtype),
            )
            sub_count = int(sub_cur.fetchone()["c"])
            ratio = 0.0 if total == 0 else round(sub_count * 100.0 / total, 2)
            return {"type_count": total, "subtype_count": sub_count, "ratio_percent": ratio}

    def count_alert_value_above(self, threshold: float, since: str, until: Optional[str] = None) -> int:
        """统计告警值超过阈值的记录数。"""
        where = ["alert_time >= ?", "TRIM(alert_value) != ''", "CAST(alert_value AS REAL) > ?"]
        params: list = [since, float(threshold)]
        if until:
            where.append("alert_time < ?")
            params.append(until)
        sql = f"SELECT COUNT(*) AS c FROM alerts WHERE {' AND '.join(where)}"
        with self._connect() as conn:
            cur = conn.execute(sql, params)
            return int(cur.fetchone()["c"])
