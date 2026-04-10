from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, unquote, urlparse
import subprocess


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS etl_import_batch (
  batch_id CHAR(36) PRIMARY KEY COMMENT '导入批次ID',
  source_name VARCHAR(64) NOT NULL COMMENT '来源类型',
  source_file VARCHAR(255) NOT NULL COMMENT '来源文件',
  started_at DATETIME NOT NULL COMMENT '开始时间',
  finished_at DATETIME NULL COMMENT '结束时间',
  status VARCHAR(32) NOT NULL COMMENT '批次状态',
  raw_row_count INT NOT NULL DEFAULT 0 COMMENT '原始行数',
  loaded_row_count INT NOT NULL DEFAULT 0 COMMENT '成功导入行数',
  note TEXT NULL COMMENT '批次说明'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='导入批次表';

CREATE TABLE IF NOT EXISTS dim_region (
  region_id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '地区主键',
  province_name VARCHAR(64) NOT NULL DEFAULT '江苏省' COMMENT '省份名称',
  city_name VARCHAR(64) NULL COMMENT '城市名称',
  county_name VARCHAR(64) NULL COMMENT '区县名称',
  town_name VARCHAR(64) NULL COMMENT '乡镇街道名称',
  region_key VARCHAR(255) NOT NULL COMMENT '地区唯一键',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  UNIQUE KEY uk_region_key (region_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='地区维表';

CREATE TABLE IF NOT EXISTS dim_device (
  device_id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '设备主键',
  device_sn VARCHAR(64) NOT NULL COMMENT '设备SN',
  device_name VARCHAR(255) NULL COMMENT '设备名称',
  device_type VARCHAR(64) NULL COMMENT '设备类型',
  city_name VARCHAR(64) NULL COMMENT '城市名称',
  county_name VARCHAR(64) NULL COMMENT '区县名称',
  town_name VARCHAR(64) NULL COMMENT '乡镇街道名称',
  longitude DECIMAL(12,6) NULL COMMENT '经度',
  latitude DECIMAL(12,6) NULL COMMENT '纬度',
  mapping_source VARCHAR(255) NULL COMMENT '映射来源文件',
  mapping_confidence VARCHAR(64) NULL COMMENT '映射可信度',
  first_seen_at DATETIME NULL COMMENT '首次观测时间',
  last_seen_at DATETIME NULL COMMENT '最近观测时间',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  UNIQUE KEY uk_device_sn (device_sn),
  KEY idx_device_region (city_name, county_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='设备维表';

CREATE TABLE IF NOT EXISTS alerts (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '告警主键',
  alert_content TEXT NULL COMMENT '告警内容',
  alert_type VARCHAR(128) NULL COMMENT '告警类型',
  alert_subtype VARCHAR(128) NULL COMMENT '告警子类型',
  alert_time DATETIME NULL COMMENT '告警时间',
  alert_level VARCHAR(64) NULL COMMENT '告警等级',
  region_code VARCHAR(64) NULL COMMENT '区域编码',
  region_name VARCHAR(128) NULL COMMENT '区域名称',
  alert_value VARCHAR(64) NULL COMMENT '告警值',
  device_code VARCHAR(64) NULL COMMENT '设备编码',
  device_name VARCHAR(255) NULL COMMENT '设备名称',
  longitude VARCHAR(64) NULL COMMENT '经度',
  latitude VARCHAR(64) NULL COMMENT '纬度',
  city VARCHAR(64) NULL COMMENT '设备所在市',
  county VARCHAR(64) NULL COMMENT '设备所在区县',
  sms_content TEXT NULL COMMENT '短信内容',
  disposal_suggestion LONGTEXT NULL COMMENT '处置建议',
  source_file VARCHAR(255) NOT NULL COMMENT '来源文件',
  source_sheet VARCHAR(128) NOT NULL COMMENT '来源工作表',
  source_row INT NOT NULL COMMENT '来源行号',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  UNIQUE KEY uk_alert_source (source_file, source_sheet, source_row),
  KEY idx_alert_time (alert_time),
  KEY idx_alert_device_time (device_code, alert_time),
  KEY idx_alert_region_time (city, county, alert_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='告警事实表';

CREATE TABLE IF NOT EXISTS metric_rule (
  rule_code VARCHAR(64) PRIMARY KEY COMMENT '规则编码',
  rule_name VARCHAR(128) NOT NULL COMMENT '规则名称',
  rule_scope VARCHAR(64) NOT NULL COMMENT '规则作用域',
  rule_definition_json JSON NOT NULL COMMENT '规则定义JSON',
  enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分析口径配置表';

CREATE TABLE IF NOT EXISTS fact_pest_monitor (
  record_id CHAR(36) PRIMARY KEY COMMENT '虫情原始记录ID',
  batch_id CHAR(36) NOT NULL COMMENT '导入批次ID',
  device_sn VARCHAR(64) NOT NULL COMMENT '设备SN',
  device_name VARCHAR(255) NULL COMMENT '设备名称',
  device_type VARCHAR(64) NULL COMMENT '设备类型',
  device_status VARCHAR(32) NULL COMMENT '设备状态',
  city_name VARCHAR(64) NULL COMMENT '城市名称',
  county_name VARCHAR(64) NULL COMMENT '区县名称',
  longitude DECIMAL(12,6) NULL COMMENT '经度',
  latitude DECIMAL(12,6) NULL COMMENT '纬度',
  pest_name_raw TEXT NULL COMMENT '原始虫种字段',
  pest_num_raw TEXT NULL COMMENT '原始虫口数字段',
  normalized_pest_names TEXT NULL COMMENT '标准化虫种列表',
  normalized_pest_count DECIMAL(12,2) NULL COMMENT '标准化虫口数量',
  severity_usable TINYINT NOT NULL DEFAULT 0 COMMENT '是否可参与严重度分析',
  data_quality_flag VARCHAR(255) NOT NULL DEFAULT 'ok' COMMENT '数据质量标记',
  monitor_time DATETIME NULL COMMENT '监测时间',
  create_time DATETIME NULL COMMENT '创建时间',
  source_file VARCHAR(255) NOT NULL COMMENT '来源文件',
  source_sheet VARCHAR(128) NOT NULL COMMENT '来源工作表',
  source_row INT NOT NULL COMMENT '来源行号',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  KEY idx_pest_time_region (monitor_time, city_name, county_name),
  KEY idx_pest_sn_time (device_sn, monitor_time),
  KEY idx_pest_score (severity_usable, normalized_pest_count)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='虫情事实表';

CREATE TABLE IF NOT EXISTS fact_soil_moisture (
  record_id CHAR(36) PRIMARY KEY COMMENT '墒情原始记录ID',
  batch_id CHAR(36) NOT NULL COMMENT '导入批次ID',
  device_sn VARCHAR(64) NOT NULL COMMENT '设备SN',
  gateway_id VARCHAR(64) NULL COMMENT '网关编号',
  sensor_id VARCHAR(64) NULL COMMENT '传感器编号',
  unit_id VARCHAR(64) NULL COMMENT '单元编号',
  city_name VARCHAR(64) NULL COMMENT '城市名称',
  county_name VARCHAR(64) NULL COMMENT '区县名称',
  town_name VARCHAR(64) NULL COMMENT '乡镇街道名称',
  device_name VARCHAR(255) NULL COMMENT '设备名称',
  longitude DECIMAL(12,6) NULL COMMENT '经度',
  latitude DECIMAL(12,6) NULL COMMENT '纬度',
  sample_time DATETIME NULL COMMENT '采样时间',
  create_time DATETIME NULL COMMENT '创建时间',
  water20cm DECIMAL(12,2) NULL COMMENT '20厘米相对含水量',
  water40cm DECIMAL(12,2) NULL COMMENT '40厘米相对含水量',
  water60cm DECIMAL(12,2) NULL COMMENT '60厘米相对含水量',
  water80cm DECIMAL(12,2) NULL COMMENT '80厘米相对含水量',
  t20cm DECIMAL(12,2) NULL COMMENT '20厘米温度',
  t40cm DECIMAL(12,2) NULL COMMENT '40厘米温度',
  t60cm DECIMAL(12,2) NULL COMMENT '60厘米温度',
  t80cm DECIMAL(12,2) NULL COMMENT '80厘米温度',
  water20cm_field_state VARCHAR(64) NULL COMMENT '20厘米含水量等级',
  water40cm_field_state VARCHAR(64) NULL COMMENT '40厘米含水量等级',
  water60cm_field_state VARCHAR(64) NULL COMMENT '60厘米含水量等级',
  water80cm_field_state VARCHAR(64) NULL COMMENT '80厘米含水量等级',
  t20cm_field_state VARCHAR(64) NULL COMMENT '20厘米温度等级',
  t40cm_field_state VARCHAR(64) NULL COMMENT '40厘米温度等级',
  t60cm_field_state VARCHAR(64) NULL COMMENT '60厘米温度等级',
  t80cm_field_state VARCHAR(64) NULL COMMENT '80厘米温度等级',
  water20cm_valid TINYINT NOT NULL DEFAULT 0 COMMENT '20厘米含水量是否有效',
  t20cm_valid TINYINT NOT NULL DEFAULT 0 COMMENT '20厘米温度是否有效',
  soil_anomaly_type VARCHAR(16) NOT NULL DEFAULT 'normal' COMMENT '墒情异常类型',
  soil_anomaly_score DECIMAL(12,2) NOT NULL DEFAULT 0 COMMENT '墒情异常评分',
  data_quality_flag VARCHAR(255) NOT NULL DEFAULT 'ok' COMMENT '数据质量标记',
  source_file VARCHAR(255) NOT NULL COMMENT '来源文件',
  source_sheet VARCHAR(128) NOT NULL COMMENT '来源工作表',
  source_row INT NOT NULL COMMENT '来源行号',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
  KEY idx_soil_time_region (sample_time, city_name, county_name),
  KEY idx_soil_sn_time (device_sn, sample_time),
  KEY idx_soil_anomaly (soil_anomaly_type, soil_anomaly_score)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='墒情事实表';
"""

DEFAULT_RULES = [
    {
        "rule_code": "soil_anomaly_v1",
        "rule_name": "第一版墒情异常阈值",
        "rule_scope": "soil",
        "rule_definition_json": json.dumps({"low_threshold": 50, "high_threshold": 150, "score_formula": "<50 => 50-x; >150 => x-150"}, ensure_ascii=False),
    },
    {
        "rule_code": "pest_severity_v1",
        "rule_name": "第一版虫情严重度规则",
        "rule_scope": "pest",
        "rule_definition_json": json.dumps({"count_rule": "单值直接取值，多值逗号拆分后求和，>10000视为异常剔除", "tie_breaker": ["记录数", "活跃天数"]}, ensure_ascii=False),
    },
]


@dataclass
class MySQLConnectionInfo:
    host: str
    port: int
    user: str
    password: str
    database: str
    params: dict


class MySQLRepository:
    def __init__(self, db_url: str):
        self.db_url = db_url
        self.conn = self._parse_url(db_url)

    @staticmethod
    def _parse_url(db_url: str) -> MySQLConnectionInfo:
        parsed = urlparse(db_url)
        if parsed.scheme not in {"mysql"}:
            raise ValueError("DOC_AGENT_DB_URL 必须是 mysql:// 连接串")
        database = parsed.path.lstrip("/")
        if not database:
            raise ValueError("DOC_AGENT_DB_URL 缺少数据库名")
        return MySQLConnectionInfo(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            database=database,
            params=parse_qs(parsed.query),
        )

    def _write_defaults_file(self) -> str:
        fd, path = tempfile.mkstemp(prefix="doc-ai-agent-mysql-", suffix=".cnf")
        content = (
            "[client]\n"
            f"host={self.conn.host}\n"
            f"port={self.conn.port}\n"
            f"user={self.conn.user}\n"
            f"password={self.conn.password}\n"
            f"database={self.conn.database}\n"
            "default-character-set=utf8mb4\n"
            "local-infile=1\n"
        )
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.chmod(path, 0o600)
        return path

    def _run_sql(self, sql: str, *, expect_output: bool = False) -> str:
        defaults_file = self._write_defaults_file()
        try:
            command = [
                "mysql",
                f"--defaults-extra-file={defaults_file}",
                "--batch",
                "--raw",
                "--skip-column-names",
                "-e",
                sql,
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "mysql command failed")
            return result.stdout.strip() if expect_output else ""
        finally:
            try:
                os.remove(defaults_file)
            except OSError:
                pass

    @staticmethod
    def _quote(value) -> str:
        if value is None:
            return "NULL"
        if isinstance(value, bool):
            return "1" if value else "0"
        if isinstance(value, (int, float)):
            return str(value)
        text = str(value)
        text = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
        return f"'{text}'"

    def _insert_many(self, table: str, columns: List[str], rows: Iterable[dict], update_columns: List[str], batch_size: int = 500) -> int:
        batch = []
        inserted = 0
        rows = list(rows)
        if not rows:
            return 0
        for row in rows:
            values_sql = "(" + ", ".join(self._quote(row.get(col)) for col in columns) + ")"
            batch.append(values_sql)
            if len(batch) >= batch_size:
                inserted += self._flush_insert(table, columns, batch, update_columns)
                batch = []
        if batch:
            inserted += self._flush_insert(table, columns, batch, update_columns)
        return inserted

    def _flush_insert(self, table: str, columns: List[str], values_sql: List[str], update_columns: List[str]) -> int:
        updates = ", ".join(f"{col}=VALUES({col})" for col in update_columns)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n"
            + ",\n".join(values_sql)
            + f"\nON DUPLICATE KEY UPDATE {updates};"
        )
        self._run_sql(sql)
        return len(values_sql)

    def create_tables(self) -> None:
        self._run_sql(SCHEMA_SQL)
        self._seed_rules()

    def structured_data_ready(self) -> bool:
        try:
            pest_count = self._fetch_int("SELECT COUNT(*) FROM fact_pest_monitor;")
            soil_count = self._fetch_int("SELECT COUNT(*) FROM fact_soil_moisture;")
            region_count = self._fetch_int("SELECT COUNT(*) FROM dim_region;")
            device_count = self._fetch_int("SELECT COUNT(*) FROM dim_device;")
        except Exception:
            return False
        return pest_count > 0 and soil_count > 0 and region_count > 0 and device_count > 0

    def _seed_rules(self) -> None:
        columns = ["rule_code", "rule_name", "rule_scope", "rule_definition_json", "enabled"]
        rows = [{**rule, "enabled": 1} for rule in DEFAULT_RULES]
        self._insert_many("metric_rule", columns, rows, ["rule_name", "rule_scope", "rule_definition_json", "enabled"])

    def begin_batch(self, source_name: str, source_file: str, note: str = "") -> str:
        batch_id = str(uuid.uuid4())
        sql = f"""
        INSERT INTO etl_import_batch (
          batch_id, source_name, source_file, started_at, status, raw_row_count, loaded_row_count, note
        ) VALUES (
          {self._quote(batch_id)}, {self._quote(source_name)}, {self._quote(source_file)}, NOW(), 'running', 0, 0, {self._quote(note)}
        );
        """
        self._run_sql(sql)
        return batch_id

    def finish_batch(self, batch_id: str, raw_row_count: int, loaded_row_count: int, status: str = "done", note: str = "") -> None:
        sql = f"""
        UPDATE etl_import_batch
        SET finished_at = NOW(), status = {self._quote(status)}, raw_row_count = {int(raw_row_count)}, loaded_row_count = {int(loaded_row_count)}, note = {self._quote(note)}
        WHERE batch_id = {self._quote(batch_id)};
        """
        self._run_sql(sql)

    def upsert_regions(self, rows: Iterable[dict]) -> int:
        dedup = {}
        for row in rows:
            key = f"江苏省|{row.get('city_name') or ''}|{row.get('county_name') or ''}|{row.get('town_name') or ''}"
            if key == "江苏省|||":
                continue
            dedup[key] = {
                "province_name": "江苏省",
                "city_name": row.get("city_name"),
                "county_name": row.get("county_name"),
                "town_name": row.get("town_name"),
                "region_key": key,
            }
        columns = ["province_name", "city_name", "county_name", "town_name", "region_key"]
        return self._insert_many("dim_region", columns, dedup.values(), ["city_name", "county_name", "town_name"])

    def upsert_devices(self, rows: Iterable[dict]) -> int:
        columns = [
            "device_sn", "device_name", "device_type", "city_name", "county_name", "town_name",
            "longitude", "latitude", "mapping_source", "mapping_confidence", "first_seen_at", "last_seen_at"
        ]
        cleaned = []
        for row in rows:
            if not row.get("device_sn"):
                continue
            cleaned.append(row)
        return self._insert_many(
            "dim_device",
            columns,
            cleaned,
            ["device_name", "device_type", "city_name", "county_name", "town_name", "longitude", "latitude", "mapping_source", "mapping_confidence", "first_seen_at", "last_seen_at"],
        )

    def bulk_upsert_pest(self, rows: Iterable[dict]) -> int:
        columns = [
            "record_id", "batch_id", "device_sn", "device_name", "device_type", "device_status", "city_name", "county_name",
            "longitude", "latitude", "pest_name_raw", "pest_num_raw", "normalized_pest_names", "normalized_pest_count",
            "severity_usable", "data_quality_flag", "monitor_time", "create_time", "source_file", "source_sheet", "source_row"
        ]
        return self._insert_many(
            "fact_pest_monitor",
            columns,
            rows,
            ["batch_id", "device_sn", "device_name", "device_type", "device_status", "city_name", "county_name", "longitude", "latitude", "pest_name_raw", "pest_num_raw", "normalized_pest_names", "normalized_pest_count", "severity_usable", "data_quality_flag", "monitor_time", "create_time", "source_file", "source_sheet", "source_row"],
        )

    def bulk_upsert_soil(self, rows: Iterable[dict]) -> int:
        columns = [
            "record_id", "batch_id", "device_sn", "gateway_id", "sensor_id", "unit_id", "city_name", "county_name", "town_name", "device_name",
            "longitude", "latitude", "sample_time", "create_time", "water20cm", "water40cm", "water60cm", "water80cm",
            "t20cm", "t40cm", "t60cm", "t80cm", "water20cm_field_state", "water40cm_field_state", "water60cm_field_state", "water80cm_field_state",
            "t20cm_field_state", "t40cm_field_state", "t60cm_field_state", "t80cm_field_state", "water20cm_valid", "t20cm_valid", "soil_anomaly_type", "soil_anomaly_score", "data_quality_flag",
            "source_file", "source_sheet", "source_row"
        ]
        return self._insert_many(
            "fact_soil_moisture",
            columns,
            rows,
            ["batch_id", "device_sn", "gateway_id", "sensor_id", "unit_id", "city_name", "county_name", "town_name", "device_name", "longitude", "latitude", "sample_time", "create_time", "water20cm", "water40cm", "water60cm", "water80cm", "t20cm", "t40cm", "t60cm", "t80cm", "water20cm_field_state", "water40cm_field_state", "water60cm_field_state", "water80cm_field_state", "t20cm_field_state", "t40cm_field_state", "t60cm_field_state", "t80cm_field_state", "water20cm_valid", "t20cm_valid", "soil_anomaly_type", "soil_anomaly_score", "data_quality_flag", "source_file", "source_sheet", "source_row"],
        )

    def enrich_soil_dimensions(self) -> None:
        sql = """
        UPDATE fact_soil_moisture s
        JOIN dim_device d ON d.device_sn = s.device_sn
        SET
          s.city_name = COALESCE(s.city_name, d.city_name),
          s.county_name = COALESCE(s.county_name, d.county_name),
          s.town_name = COALESCE(s.town_name, d.town_name),
          s.device_name = COALESCE(s.device_name, d.device_name),
          s.longitude = COALESCE(s.longitude, d.longitude),
          s.latitude = COALESCE(s.latitude, d.latitude)
        WHERE s.city_name IS NULL OR s.county_name IS NULL OR s.device_name IS NULL;
        """
        self._run_sql(sql)

    def _fetch_json(self, sql: str):
        output = self._run_sql(sql, expect_output=True)
        if not output:
            return []
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    def _fetch_json_object(self, sql: str):
        output = self._run_sql(sql, expect_output=True)
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None

    def _fetch_int(self, sql: str) -> int:
        output = self._run_sql(sql, expect_output=True)
        return int(output or 0)

    def insert_alerts(self, rows: Iterable[dict]) -> int:
        columns = [
            "alert_content",
            "alert_type",
            "alert_subtype",
            "alert_time",
            "alert_level",
            "region_code",
            "region_name",
            "alert_value",
            "device_code",
            "device_name",
            "longitude",
            "latitude",
            "city",
            "county",
            "sms_content",
            "disposal_suggestion",
            "source_file",
            "source_sheet",
            "source_row",
        ]
        payload = []
        for row in rows:
            source_file = row.get("source_file")
            source_sheet = row.get("source_sheet")
            source_row = row.get("source_row")
            if not source_file or not source_sheet or source_row in {None, ""}:
                continue
            payload.append(row)
        return self._insert_many(
            "alerts",
            columns,
            payload,
            [
                "alert_content",
                "alert_type",
                "alert_subtype",
                "alert_time",
                "alert_level",
                "region_code",
                "region_name",
                "alert_value",
                "device_code",
                "device_name",
                "longitude",
                "latitude",
                "city",
                "county",
                "sms_content",
                "disposal_suggestion",
            ],
        )

    def top_n(self, field: str, n: int, since: str) -> List[dict]:
        return self.top_n_filtered(field, n, since)

    def sample_alerts(self, since: str, limit: int = 3) -> List[dict]:
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
            'city', city,
            'county', county,
            'alert_type', alert_type,
            'alert_level', alert_level,
            'alert_content', alert_content,
            'source_file', source_file,
            'source_sheet', source_sheet,
            'source_row', source_row
          ) AS item
          FROM alerts
          WHERE alert_time >= {self._quote(since)}
          ORDER BY alert_time DESC
          LIMIT {max(1, int(limit))}
        ) q;
        """
        return self._fetch_json(sql)

    def available_alert_time_range(self) -> Optional[dict]:
        sql = """
        SELECT JSON_OBJECT(
          'min_time', DATE_FORMAT(MIN(alert_time), '%Y-%m-%d %H:%i:%s'),
          'max_time', DATE_FORMAT(MAX(alert_time), '%Y-%m-%d %H:%i:%s')
        )
        FROM alerts
        WHERE alert_time IS NOT NULL;
        """
        result = self._fetch_json_object(sql)
        if not result or not result.get("min_time") or not result.get("max_time"):
            return None
        return {
            "min_time": str(result["min_time"]),
            "max_time": str(result["max_time"]),
        }

    def avg_alert_value_by_level(self, since: str) -> List[dict]:
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'level', level,
            'avg_alert_value', avg_alert_value,
            'count', cnt
          ) AS item
          FROM (
            SELECT
              alert_level AS level,
              ROUND(AVG(CAST(alert_value AS DECIMAL(12,2))), 2) AS avg_alert_value,
              COUNT(*) AS cnt
            FROM alerts
            WHERE alert_time >= {self._quote(since)}
              AND alert_value IS NOT NULL
              AND TRIM(alert_value) != ''
            GROUP BY alert_level
            ORDER BY avg_alert_value DESC, level ASC
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def devices_triggered_on_multiple_days(self, since: str, min_days: int = 2, limit: int = 50) -> List[dict]:
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'device_code', device_code,
            'device_name', device_name,
            'active_days', day_cnt,
            'first_day', first_day,
            'last_day', last_day
          ) AS item
          FROM (
            SELECT
              device_code,
              MAX(device_name) AS device_name,
              COUNT(DISTINCT DATE(alert_time)) AS day_cnt,
              DATE_FORMAT(MIN(DATE(alert_time)), '%Y-%m-%d') AS first_day,
              DATE_FORMAT(MAX(DATE(alert_time)), '%Y-%m-%d') AS last_day
            FROM alerts
            WHERE alert_time >= {self._quote(since)}
              AND device_code IS NOT NULL
              AND TRIM(device_code) != ''
            GROUP BY device_code
            HAVING day_cnt >= {max(2, int(min_days))}
            ORDER BY day_cnt DESC, device_code ASC
            LIMIT {max(1, int(limit))}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def count_filtered(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        level: Optional[str] = None,
    ) -> int:
        where = [f"alert_time >= {self._quote(since)}"]
        if until:
            where.append(f"alert_time < {self._quote(until)}")
        if city:
            where.append(f"city = {self._quote(city)}")
        if level:
            where.append(f"alert_level = {self._quote(level)}")
        return self._fetch_int(f"SELECT COUNT(*) FROM alerts WHERE {' AND '.join(where)};")

    def top_n_filtered(
        self,
        field: str,
        n: int,
        since: str,
        until: Optional[str] = None,
        min_alert_value: Optional[float] = None,
    ) -> List[dict]:
        allowed = {"city", "county", "alert_type", "alert_level"}
        if field not in allowed:
            raise ValueError("unsupported field")
        where = [f"alert_time >= {self._quote(since)}"]
        if until:
            where.append(f"alert_time < {self._quote(until)}")
        if min_alert_value is not None:
            where.extend(
                [
                    "alert_value IS NOT NULL",
                    "TRIM(alert_value) != ''",
                    f"CAST(alert_value AS DECIMAL(12,2)) > {self._quote(float(min_alert_value))}",
                ]
            )
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT('name', name, 'count', cnt) AS item
          FROM (
            SELECT {field} AS name, COUNT(*) AS cnt
            FROM alerts
            WHERE {' AND '.join(where)}
            GROUP BY {field}
            ORDER BY cnt DESC, name ASC
            LIMIT {max(1, int(n))}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def highest_alert_values(self, limit: int = 10, since: Optional[str] = None) -> List[dict]:
        where = ["alert_value IS NOT NULL", "TRIM(alert_value) != ''"]
        if since:
            where.append(f"alert_time >= {self._quote(since)}")
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
            'device_code', device_code,
            'device_name', device_name,
            'city', city,
            'county', county,
            'alert_value', CAST(alert_value AS DECIMAL(12,2))
          ) AS item
          FROM alerts
          WHERE {' AND '.join(where)}
          ORDER BY CAST(alert_value AS DECIMAL(12,2)) DESC, alert_time DESC
          LIMIT {max(1, int(limit))}
        ) q;
        """
        return self._fetch_json(sql)

    def latest_by_device(self, device_code: str) -> Optional[dict]:
        sql = f"""
        SELECT JSON_OBJECT(
          'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
          'alert_level', alert_level,
          'disposal_suggestion', disposal_suggestion,
          'city', city,
          'county', county,
          'device_code', device_code,
          'device_name', device_name
        )
        FROM alerts
        WHERE device_code = {self._quote(device_code)}
        ORDER BY alert_time DESC
        LIMIT 1;
        """
        return self._fetch_json_object(sql)

    def latest_by_region_keyword(self, city_or_county_keyword: str, region_keyword: str) -> Optional[dict]:
        sql = f"""
        SELECT JSON_OBJECT(
          'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
          'alert_level', alert_level,
          'disposal_suggestion', disposal_suggestion,
          'city', city,
          'county', county,
          'region_name', region_name,
          'device_code', device_code
        )
        FROM alerts
        WHERE (city = {self._quote(city_or_county_keyword)} OR county = {self._quote(city_or_county_keyword)})
          AND region_name LIKE {self._quote(f'%{region_keyword}%')}
        ORDER BY alert_time DESC
        LIMIT 1;
        """
        return self._fetch_json_object(sql)

    def sms_empty_records(self, county_keyword: str, limit: int = 20) -> List[dict]:
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
            'city', city,
            'county', county,
            'device_code', device_code,
            'alert_level', alert_level
          ) AS item
          FROM alerts
          WHERE county = {self._quote(county_keyword)}
            AND (sms_content IS NULL OR TRIM(sms_content) = '')
          ORDER BY alert_time DESC
          LIMIT {max(1, int(limit))}
        ) q;
        """
        return self._fetch_json(sql)

    def subtype_ratio(self, alert_type: str, alert_subtype: str, since: str) -> dict:
        total = self._fetch_int(
            f"SELECT COUNT(*) FROM alerts WHERE alert_time >= {self._quote(since)} AND alert_type = {self._quote(alert_type)};"
        )
        sub_count = self._fetch_int(
            f"SELECT COUNT(*) FROM alerts WHERE alert_time >= {self._quote(since)} AND alert_type = {self._quote(alert_type)} AND alert_subtype = {self._quote(alert_subtype)};"
        )
        ratio = 0.0 if total == 0 else round(sub_count * 100.0 / total, 2)
        return {"type_count": total, "subtype_count": sub_count, "ratio_percent": ratio}

    def count_alert_value_above(self, threshold: float, since: str, until: Optional[str] = None) -> int:
        where = [
            f"alert_time >= {self._quote(since)}",
            "alert_value IS NOT NULL",
            "TRIM(alert_value) != ''",
            f"CAST(alert_value AS DECIMAL(12,2)) > {self._quote(float(threshold))}",
        ]
        if until:
            where.append(f"alert_time < {self._quote(until)}")
        return self._fetch_int(f"SELECT COUNT(*) FROM alerts WHERE {' AND '.join(where)};")

    def sample_pest_records(self, since: str, until: Optional[str], limit: int = 3) -> List[dict]:
        until_sql = f"AND monitor_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'monitor_time', DATE_FORMAT(monitor_time, '%Y-%m-%d %H:%i:%s'),
            'city_name', city_name,
            'county_name', county_name,
            'device_name', device_name,
            'pest_name_raw', pest_name_raw,
            'normalized_pest_count', normalized_pest_count,
            'data_quality_flag', data_quality_flag
          ) AS item
          FROM fact_pest_monitor
          WHERE monitor_time >= {self._quote(since)} {until_sql}
          ORDER BY monitor_time DESC
          LIMIT {int(limit)}
        ) q;
        """
        return self._fetch_json(sql)

    def sample_soil_records(self, since: str, until: Optional[str], limit: int = 3) -> List[dict]:
        until_sql = f"AND sample_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'sample_time', DATE_FORMAT(sample_time, '%Y-%m-%d %H:%i:%s'),
            'city_name', city_name,
            'county_name', county_name,
            'device_sn', device_sn,
            'water20cm', water20cm,
            'soil_anomaly_type', soil_anomaly_type,
            'soil_anomaly_score', soil_anomaly_score
          ) AS item
          FROM fact_soil_moisture
          WHERE sample_time >= {self._quote(since)} {until_sql}
          ORDER BY sample_time DESC
          LIMIT {int(limit)}
        ) q;
        """
        return self._fetch_json(sql)

    def available_pest_time_range(self) -> Optional[dict]:
        sql = """
        SELECT JSON_OBJECT(
          'min_time', DATE_FORMAT(MIN(monitor_time), '%Y-%m-%d %H:%i:%s'),
          'max_time', DATE_FORMAT(MAX(monitor_time), '%Y-%m-%d %H:%i:%s')
        )
        FROM fact_pest_monitor
        WHERE severity_usable = 1
          AND monitor_time IS NOT NULL;
        """
        result = self._fetch_json_object(sql)
        if not result or not result.get("min_time") or not result.get("max_time"):
            return None
        return {
            "min_time": str(result["min_time"]),
            "max_time": str(result["max_time"]),
        }

    def available_soil_time_range(self, anomaly_direction: Optional[str] = None) -> Optional[dict]:
        where = ["water20cm_valid = 1", "sample_time IS NOT NULL"]
        if anomaly_direction in {"low", "high"}:
            where.append(f"soil_anomaly_type = {self._quote(anomaly_direction)}")
        sql = f"""
        SELECT JSON_OBJECT(
          'min_time', DATE_FORMAT(MIN(sample_time), '%Y-%m-%d %H:%i:%s'),
          'max_time', DATE_FORMAT(MAX(sample_time), '%Y-%m-%d %H:%i:%s')
        )
        FROM fact_soil_moisture
        WHERE {' AND '.join(where)};
        """
        result = self._fetch_json_object(sql)
        if not result or not result.get("min_time") or not result.get("max_time"):
            return None
        return {
            "min_time": str(result["min_time"]),
            "max_time": str(result["max_time"]),
        }

    def top_pest_regions(self, since: str, until: Optional[str], region_level: str = "city", top_n: int = 5):
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND monitor_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'region_name', region_name,
            'severity_score', severity_score,
            'record_count', record_count,
            'active_days', active_days
          ) AS item
          FROM (
            SELECT
              COALESCE({region_col}, '未知地区') AS region_name,
              ROUND(SUM(normalized_pest_count), 2) AS severity_score,
              COUNT(*) AS record_count,
              COUNT(DISTINCT DATE(monitor_time)) AS active_days
            FROM fact_pest_monitor
            WHERE severity_usable = 1
              AND monitor_time >= {self._quote(since)}
              {until_sql}
            GROUP BY COALESCE({region_col}, '未知地区')
            ORDER BY severity_score DESC, record_count DESC, active_days DESC, region_name ASC
            LIMIT {int(top_n)}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def top_soil_regions(self, since: str, until: Optional[str], region_level: str = "city", top_n: int = 5, anomaly_direction: Optional[str] = None):
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND sample_time < {self._quote(until)}" if until else ""
        direction_sql = f"AND soil_anomaly_type = {self._quote(anomaly_direction)}" if anomaly_direction in {"low", "high"} else "AND soil_anomaly_type IN (\'low\', \'high\')"
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'region_name', region_name,
            'anomaly_score', anomaly_score,
            'abnormal_count', abnormal_count,
            'low_count', low_count,
            'high_count', high_count
          ) AS item
          FROM (
            SELECT
              COALESCE({region_col}, '未知地区') AS region_name,
              ROUND(SUM(soil_anomaly_score), 2) AS anomaly_score,
              COUNT(*) AS abnormal_count,
              SUM(CASE WHEN soil_anomaly_type = 'low' THEN 1 ELSE 0 END) AS low_count,
              SUM(CASE WHEN soil_anomaly_type = 'high' THEN 1 ELSE 0 END) AS high_count
            FROM fact_soil_moisture
            WHERE water20cm_valid = 1
              AND sample_time >= {self._quote(since)}
              {until_sql}
              {direction_sql}
            GROUP BY COALESCE({region_col}, '未知地区')
            ORDER BY anomaly_score DESC, abnormal_count DESC, region_name ASC
            LIMIT {int(top_n)}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def pest_trend(self, since: str, until: Optional[str], region_name: str, region_level: str = "city"):
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND monitor_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'bucket', DATE_FORMAT(day_bucket, '%Y-%m-%d'),
            'severity_score', severity_score,
            'record_count', record_count
          ) AS item
          FROM (
            SELECT
              DATE(monitor_time) AS day_bucket,
              ROUND(SUM(normalized_pest_count), 2) AS severity_score,
              COUNT(*) AS record_count
            FROM fact_pest_monitor
            WHERE severity_usable = 1
              AND {region_col} = {self._quote(region_name)}
              AND monitor_time >= {self._quote(since)}
              {until_sql}
            GROUP BY DATE(monitor_time)
            ORDER BY day_bucket
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def soil_trend(self, since: str, until: Optional[str], region_name: str, region_level: str = "city"):
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND sample_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'bucket', DATE_FORMAT(day_bucket, '%Y-%m-%d'),
            'avg_water20cm', avg_water20cm,
            'avg_anomaly_score', avg_anomaly_score,
            'abnormal_count', abnormal_count
          ) AS item
          FROM (
            SELECT
              DATE(sample_time) AS day_bucket,
              ROUND(AVG(water20cm), 2) AS avg_water20cm,
              ROUND(AVG(soil_anomaly_score), 2) AS avg_anomaly_score,
              SUM(CASE WHEN soil_anomaly_type IN ('low','high') THEN 1 ELSE 0 END) AS abnormal_count
            FROM fact_soil_moisture
            WHERE water20cm_valid = 1
              AND {region_col} = {self._quote(region_name)}
              AND sample_time >= {self._quote(since)}
              {until_sql}
            GROUP BY DATE(sample_time)
            ORDER BY day_bucket
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def joint_risk_regions(self, since: str, until: Optional[str], region_level: str = "city", top_n: int = 5):
        region_col = "county_name" if region_level == "county" else "city_name"
        until_pest = f"AND monitor_time < {self._quote(until)}" if until else ""
        until_soil = f"AND sample_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'region_name', region_name,
            'pest_score', pest_score,
            'low_soil_score', low_soil_score,
            'joint_score', joint_score
          ) AS item
          FROM (
            SELECT
              p.region_name,
              p.pest_score,
              s.low_soil_score,
              ROUND(p.pest_score + s.low_soil_score, 2) AS joint_score
            FROM (
              SELECT COALESCE({region_col}, '未知地区') AS region_name, ROUND(SUM(normalized_pest_count), 2) AS pest_score
              FROM fact_pest_monitor
              WHERE severity_usable = 1
                AND monitor_time >= {self._quote(since)}
                {until_pest}
              GROUP BY COALESCE({region_col}, '未知地区')
            ) p
            JOIN (
              SELECT COALESCE({region_col}, '未知地区') AS region_name, ROUND(SUM(soil_anomaly_score), 2) AS low_soil_score
              FROM fact_soil_moisture
              WHERE water20cm_valid = 1
                AND soil_anomaly_type = 'low'
                AND sample_time >= {self._quote(since)}
                {until_soil}
              GROUP BY COALESCE({region_col}, '未知地区')
            ) s ON s.region_name = p.region_name
            ORDER BY joint_score DESC, p.region_name ASC
            LIMIT {int(top_n)}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def count_since(self, since: str) -> int:
        return self._fetch_int(f"SELECT COUNT(*) FROM alerts WHERE alert_time >= {self._quote(since)};")
