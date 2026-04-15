"""MySQL 仓储实现。

该模块负责 doc-ai-agent 的结构化数据落库与分析查询，核心职责：
- 建表与默认规则初始化
- 批量 Upsert（设备、区域、虫情、墒情、告警）
- 提供面向上层问答/分析的聚合查询接口

说明：本文件包含较多 SQL 模板，注释重点放在“为什么这么做”，
帮助对 Python/SQL 还不熟悉的同学快速理解数据流。
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime
import hashlib
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

CREATE TABLE IF NOT EXISTS auth_user (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '用户主键',
  username VARCHAR(64) NOT NULL COMMENT '用户名',
  password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希',
  password_salt VARCHAR(255) NOT NULL COMMENT '密码盐',
  is_active TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用',
  created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  UNIQUE KEY uk_auth_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='认证用户表';

CREATE TABLE IF NOT EXISTS auth_session (
  id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '会话主键',
  user_id BIGINT NOT NULL COMMENT '用户主键',
  token_hash VARCHAR(255) NOT NULL COMMENT '令牌哈希',
  created_at DATETIME NOT NULL COMMENT '创建时间',
  expires_at DATETIME NOT NULL COMMENT '过期时间',
  last_used_at DATETIME NOT NULL COMMENT '最近使用时间',
  UNIQUE KEY uk_auth_token_hash (token_hash),
  KEY idx_auth_session_user (user_id),
  CONSTRAINT fk_auth_session_user FOREIGN KEY (user_id) REFERENCES auth_user(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='认证会话表';
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
    """MySQL 连接参数对象（由连接串解析得到）。"""

    host: str
    port: int
    user: str
    password: str
    database: str
    params: dict


class MySQLRepository:
    """MySQL 数据仓储。

    该类通过命令行 `mysql` 客户端执行 SQL，而不是直接使用驱动连接。
    这样可在部署环境中复用现有客户端配置，同时减少 Python 依赖。
    """

    def __init__(self, db_url: str):
        """初始化仓储并解析连接串。"""
        self.db_url = db_url
        self.conn = self._parse_url(db_url)

    def backend_label(self) -> str:
        """返回仓储后端标签，便于上层统一展示。"""
        return "MySQL"

    @staticmethod
    def _hash_token(token: str) -> str:
        """对会话令牌做 SHA-256 哈希，避免 MySQL 中存明文。"""
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_url(db_url: str) -> MySQLConnectionInfo:
        """解析 `mysql://` 连接串，返回结构化连接信息。"""
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
        """生成临时 MySQL defaults 文件，避免密码出现在命令行参数中。"""
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
        """执行 SQL 并返回输出（可选）。

        `expect_output=False` 适合 DDL/DML；
        `expect_output=True` 适合 `SELECT` 查询。
        """
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
        """将 Python 值安全转成 SQL 字面量。"""
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
        """按批次执行 `INSERT ... ON DUPLICATE KEY UPDATE`。"""
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
        """把单个批次的 SQL 真正落库。"""
        updates = ", ".join(f"{col}=VALUES({col})" for col in update_columns)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES\n"
            + ",\n".join(values_sql)
            + f"\nON DUPLICATE KEY UPDATE {updates};"
        )
        self._run_sql(sql)
        return len(values_sql)

    def create_tables(self) -> None:
        """创建所有业务表，并初始化默认分析规则。"""
        self._run_sql(SCHEMA_SQL)
        self._seed_rules()

    def get_user_by_username(self, username: str) -> dict | None:
        """按用户名查询认证用户。"""
        sql = f"""
        SELECT JSON_OBJECT(
          'id', id,
          'username', username,
          'password_hash', password_hash,
          'password_salt', password_salt,
          'is_active', is_active
        )
        FROM auth_user
        WHERE username = {self._quote(username)}
        LIMIT 1;
        """
        return self._fetch_json_object(sql)

    def create_user(self, username: str, password_hash: str, password_salt: str) -> dict:
        """创建认证用户并返回创建结果。"""
        sql = f"""
        INSERT INTO auth_user (username, password_hash, password_salt, is_active, created_at, updated_at)
        VALUES (
          {self._quote(username)},
          {self._quote(password_hash)},
          {self._quote(password_salt)},
          1,
          NOW(),
          NOW()
        );
        """
        self._run_sql(sql)
        user = self.get_user_by_username(username)
        if user is None:
            raise RuntimeError("user creation failed")
        return user

    def update_user_password(self, user_id: int, password_hash: str, password_salt: str) -> None:
        """更新认证用户密码。"""
        sql = f"""
        UPDATE auth_user
        SET password_hash = {self._quote(password_hash)},
            password_salt = {self._quote(password_salt)},
            updated_at = NOW()
        WHERE id = {int(user_id)};
        """
        self._run_sql(sql)

    def create_session(self, user_id: int, token: str, expires_at: str) -> str:
        """创建认证会话并返回原始 token。"""
        sql = f"""
        INSERT INTO auth_session (user_id, token_hash, created_at, expires_at, last_used_at)
        VALUES (
          {int(user_id)},
          {self._quote(self._hash_token(token))},
          NOW(),
          {self._quote(expires_at)},
          NOW()
        );
        """
        self._run_sql(sql)
        return token

    def get_user_by_token(self, token: str) -> dict | None:
        """通过 token 查询认证用户，并刷新最近使用时间。"""
        token_hash = self._hash_token(token)
        sql = f"""
        SELECT JSON_OBJECT(
          'id', u.id,
          'username', u.username,
          'is_active', u.is_active,
          'session_id', s.id
        )
        FROM auth_session s
        JOIN auth_user u ON u.id = s.user_id
        WHERE s.token_hash = {self._quote(token_hash)}
          AND s.expires_at > NOW()
          AND u.is_active = 1
        LIMIT 1;
        """
        user = self._fetch_json_object(sql)
        if user:
            touch_sql = f"""
            UPDATE auth_session SET last_used_at = NOW()
            WHERE id = {int(user['session_id'])};
            """
            self._run_sql(touch_sql)
        return user

    def delete_session(self, token: str) -> None:
        """删除认证会话。"""
        sql = f"""
        DELETE FROM auth_session
        WHERE token_hash = {self._quote(self._hash_token(token))};
        """
        self._run_sql(sql)

    def structured_data_ready(self) -> bool:
        """检查结构化数据是否已经准备完成。"""
        try:
            pest_count = self._fetch_int("SELECT COUNT(*) FROM fact_pest_monitor;")
            soil_count = self._fetch_int("SELECT COUNT(*) FROM fact_soil_moisture;")
            region_count = self._fetch_int("SELECT COUNT(*) FROM dim_region;")
            device_count = self._fetch_int("SELECT COUNT(*) FROM dim_device;")
        except Exception:
            return False
        return pest_count > 0 and soil_count > 0 and region_count > 0 and device_count > 0

    def _seed_rules(self) -> None:
        """写入默认指标规则（幂等更新）。"""
        columns = ["rule_code", "rule_name", "rule_scope", "rule_definition_json", "enabled"]
        rows = [{**rule, "enabled": 1} for rule in DEFAULT_RULES]
        self._insert_many("metric_rule", columns, rows, ["rule_name", "rule_scope", "rule_definition_json", "enabled"])

    def begin_batch(self, source_name: str, source_file: str, note: str = "") -> str:
        """开始一次 ETL 导入批次，返回批次 ID。"""
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
        """结束导入批次并记录统计信息。"""
        sql = f"""
        UPDATE etl_import_batch
        SET finished_at = NOW(), status = {self._quote(status)}, raw_row_count = {int(raw_row_count)}, loaded_row_count = {int(loaded_row_count)}, note = {self._quote(note)}
        WHERE batch_id = {self._quote(batch_id)};
        """
        self._run_sql(sql)

    def upsert_regions(self, rows: Iterable[dict]) -> int:
        """区域维度去重并 Upsert。"""
        dedup = {}
        for row in rows:
            key = f"江苏省|{row.get('city_name') or ''}|{row.get('county_name') or ''}|{row.get('town_name') or ''}"
            if key == "江苏省|||":
                # 全空地区没有分析价值，直接跳过。
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
        """设备维度 Upsert，仅保留具备 device_sn 的记录。"""
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
        """批量写入虫情事实表。"""
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
        """批量写入墒情事实表。"""
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
        """使用设备维表补齐墒情记录中缺失的维度信息。"""
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
        """执行查询并解析为 JSON 数组，异常时兜底为空列表。"""
        output = self._run_sql(sql, expect_output=True)
        if not output:
            return []
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return []

    def _fetch_json_object(self, sql: str):
        """执行查询并解析为 JSON 对象，异常时返回 `None`。"""
        output = self._run_sql(sql, expect_output=True)
        if not output:
            return None
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            return None

    def _fetch_int(self, sql: str) -> int:
        """执行整型聚合查询。"""
        output = self._run_sql(sql, expect_output=True)
        return int(output or 0)

    def insert_alerts(self, rows: Iterable[dict]) -> int:
        """批量写入告警事实表，过滤掉缺少来源主键的脏数据。"""
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
        """兼容旧调用：按字段统计 TopN。"""
        return self.top_n_filtered(field, n, since)

    def sample_alerts(self, since: str, limit: int = 3) -> List[dict]:
        """获取告警样本，用于摘要展示。"""
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
        """查询告警时间覆盖范围。"""
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
        """按告警等级统计平均告警值。"""
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
        """统计在多个自然日触发告警的设备。"""
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
        """按时间与维度条件统计告警数量。"""
        where = [f"alert_time >= {self._quote(since)}"]
        if until:
            where.append(f"alert_time < {self._quote(until)}")
        if city:
            where.append(f"city = {self._quote(city)}")
        if level:
            where.append(f"alert_level = {self._quote(level)}")
        return self._fetch_int(f"SELECT COUNT(*) FROM alerts WHERE {' AND '.join(where)};")

    def alerts_trend(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
    ) -> List[dict]:
        """按天聚合告警趋势。"""
        where = [f"alert_time >= {self._quote(since)}"]
        if until:
            where.append(f"alert_time < {self._quote(until)}")
        if city:
            where.append(f"city = {self._quote(city)}")
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'date', DATE_FORMAT(day_bucket, '%Y-%m-%d'),
            'alert_count', alert_count
          ) AS item
          FROM (
            SELECT
              DATE(alert_time) AS day_bucket,
              COUNT(*) AS alert_count
            FROM alerts
            WHERE {' AND '.join(where)}
            GROUP BY DATE(alert_time)
            ORDER BY day_bucket ASC
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def top_n_filtered(
        self,
        field: str,
        n: int,
        since: str,
        until: Optional[str] = None,
        min_alert_value: Optional[float] = None,
    ) -> List[dict]:
        """支持时间窗与阈值过滤的 TopN 统计。"""
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
        """查询告警值最高的记录。"""
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
        """按设备编码查询最新一条告警。"""
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

    def latest_soil_by_device(self, device_code: str) -> Optional[dict]:
        """按设备编码查询最新一条墒情记录。"""
        sql = f"""
        SELECT JSON_OBJECT(
          'device_sn', device_sn,
          'device_name', device_name,
          'city_name', city_name,
          'county_name', county_name,
          'sample_time', DATE_FORMAT(sample_time, '%Y-%m-%d %H:%i:%s'),
          'soil_anomaly_type', soil_anomaly_type,
          'soil_anomaly_score', CAST(soil_anomaly_score AS DECIMAL(12,2))
        )
        FROM fact_soil_moisture
        WHERE device_sn = {self._quote(device_code)}
        ORDER BY sample_time DESC
        LIMIT 1;
        """
        return self._fetch_json_object(sql)

    def abnormal_soil_devices(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
        limit: int = 10,
    ) -> List[dict]:
        """查询指定时间窗内出现过墒情异常的设备。"""
        where = [
            "soil_anomaly_type IN ('low', 'high')",
            f"sample_time >= {self._quote(since)}",
        ]
        if until:
            where.append(f"sample_time < {self._quote(until)}")
        if city:
            where.append(f"city_name = {self._quote(city)}")
        if county:
            where.append(f"county_name = {self._quote(county)}")
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'device_sn', device_sn,
            'device_name', device_name,
            'city_name', city_name,
            'county_name', county_name,
            'abnormal_count', abnormal_count,
            'last_sample_time', DATE_FORMAT(last_sample_time, '%Y-%m-%d %H:%i:%s')
          ) AS item
          FROM (
            SELECT
              device_sn,
              MAX(device_name) AS device_name,
              MAX(city_name) AS city_name,
              MAX(county_name) AS county_name,
              COUNT(*) AS abnormal_count,
              MAX(sample_time) AS last_sample_time
            FROM fact_soil_moisture
            WHERE {' AND '.join(where)}
            GROUP BY device_sn
            ORDER BY abnormal_count DESC, last_sample_time DESC, device_sn ASC
            LIMIT {max(1, int(limit))}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def soil_anomaly_devices_without_alerts(
        self,
        since: str,
        until: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
        limit: int = 10,
    ) -> List[dict]:
        """查询有墒情异常但无告警的设备。"""
        soil_where = [
            "s.soil_anomaly_type IN ('low', 'high')",
            f"s.sample_time >= {self._quote(since)}",
        ]
        alert_where = [f"a.alert_time >= {self._quote(since)}"]
        if until:
            soil_where.append(f"s.sample_time < {self._quote(until)}")
            alert_where.append(f"a.alert_time < {self._quote(until)}")
        if city:
            soil_where.append(f"s.city_name = {self._quote(city)}")
        if county:
            soil_where.append(f"s.county_name = {self._quote(county)}")
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'device_sn', device_sn,
            'device_name', device_name,
            'city_name', city_name,
            'county_name', county_name,
            'abnormal_count', abnormal_count,
            'last_sample_time', DATE_FORMAT(last_sample_time, '%Y-%m-%d %H:%i:%s')
          ) AS item
          FROM (
            SELECT
              s.device_sn,
              MAX(s.device_name) AS device_name,
              MAX(s.city_name) AS city_name,
              MAX(s.county_name) AS county_name,
              COUNT(*) AS abnormal_count,
              MAX(s.sample_time) AS last_sample_time
            FROM fact_soil_moisture s
            LEFT JOIN alerts a
              ON a.device_code = s.device_sn
             AND {' AND '.join(alert_where)}
            WHERE {' AND '.join(soil_where)}
              AND a.device_code IS NULL
            GROUP BY s.device_sn
            ORDER BY abnormal_count DESC, last_sample_time DESC, s.device_sn ASC
            LIMIT {max(1, int(limit))}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def latest_by_region_keyword(self, city_or_county_keyword: str, region_keyword: str) -> Optional[dict]:
        """按地区+区域关键词查询最新告警。"""
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
        """查询短信内容为空的告警记录。"""
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

    def top_active_devices(self, since: str, until: Optional[str] = None, limit: int = 10) -> List[dict]:
        """统计时间窗内最活跃的告警设备。"""
        until_sql = f"AND alert_time < {self._quote(until)}" if until else ""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'device_code', device_code,
            'device_name', device_name,
            'alert_count', alert_count,
            'active_days', active_days,
            'last_alert_time', last_alert_time
          ) AS item
          FROM (
            SELECT
              device_code,
              device_name,
              COUNT(*) AS alert_count,
              COUNT(DISTINCT DATE(alert_time)) AS active_days,
              DATE_FORMAT(MAX(alert_time), '%Y-%m-%d %H:%i:%s') AS last_alert_time
            FROM alerts
            WHERE alert_time >= {self._quote(since)}
              {until_sql}
              AND device_code IS NOT NULL
              AND TRIM(device_code) != ''
            GROUP BY device_code, device_name
            ORDER BY alert_count DESC, active_days DESC, MAX(alert_time) DESC, device_code ASC
            LIMIT {max(1, int(limit))}
          ) ranked
        ) q;
        """
        return self._fetch_json(sql)

    def unknown_region_devices(self, limit: int = 20) -> List[dict]:
        """查询地区信息缺失或未知的设备。"""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'device_code', device_code,
            'device_name', device_name,
            'alert_count', alert_count,
            'last_alert_time', last_alert_time
          ) AS item
          FROM (
            SELECT
              device_code,
              device_name,
              COUNT(*) AS alert_count,
              DATE_FORMAT(MAX(alert_time), '%Y-%m-%d %H:%i:%s') AS last_alert_time
            FROM alerts
            WHERE device_code IS NOT NULL
              AND TRIM(device_code) != ''
              AND (
                city IS NULL OR TRIM(city) = ''
                OR county IS NULL OR TRIM(county) = ''
                OR county IN ('未知地区', '未知区域', '未知区')
              )
            GROUP BY device_code, device_name
            ORDER BY alert_count DESC, MAX(alert_time) DESC, device_code ASC
            LIMIT {max(1, int(limit))}
          ) ranked
        ) q;
        """
        return self._fetch_json(sql)

    def empty_county_records(self, limit: int = 20) -> List[dict]:
        """查询区县字段为空的告警明细。"""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
            'city', city,
            'county', county,
            'region_name', region_name,
            'device_code', device_code,
            'device_name', device_name,
            'alert_level', alert_level
          ) AS item
          FROM alerts
          WHERE county IS NULL OR TRIM(county) = ''
          ORDER BY alert_time DESC
          LIMIT {max(1, int(limit))}
        ) q;
        """
        return self._fetch_json(sql)

    def unmatched_region_records(self, limit: int = 20) -> List[dict]:
        """查询城市/区县/区域名任一缺失的记录。"""
        sql = f"""
        SELECT COALESCE(JSON_ARRAYAGG(item), JSON_ARRAY())
        FROM (
          SELECT JSON_OBJECT(
            'alert_time', DATE_FORMAT(alert_time, '%Y-%m-%d %H:%i:%s'),
            'city', city,
            'county', county,
            'region_name', region_name,
            'device_code', device_code,
            'device_name', device_name,
            'alert_level', alert_level
          ) AS item
          FROM alerts
          WHERE city IS NULL OR TRIM(city) = ''
             OR county IS NULL OR TRIM(county) = ''
             OR region_name IS NULL OR TRIM(region_name) = ''
          ORDER BY alert_time DESC
          LIMIT {max(1, int(limit))}
        ) q;
        """
        return self._fetch_json(sql)

    def subtype_ratio(self, alert_type: str, alert_subtype: str, since: str) -> dict:
        """计算某主类型下子类型占比。"""
        total = self._fetch_int(
            f"SELECT COUNT(*) FROM alerts WHERE alert_time >= {self._quote(since)} AND alert_type = {self._quote(alert_type)};"
        )
        sub_count = self._fetch_int(
            f"SELECT COUNT(*) FROM alerts WHERE alert_time >= {self._quote(since)} AND alert_type = {self._quote(alert_type)} AND alert_subtype = {self._quote(alert_subtype)};"
        )
        ratio = 0.0 if total == 0 else round(sub_count * 100.0 / total, 2)
        return {"type_count": total, "subtype_count": sub_count, "ratio_percent": ratio}

    def count_alert_value_above(self, threshold: float, since: str, until: Optional[str] = None) -> int:
        """统计告警值超过阈值的记录数。"""
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
        """获取虫情样本记录。"""
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
        """获取墒情样本记录。"""
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
        """查询可用虫情时间范围。"""
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
        """查询可用墒情时间范围，可按异常方向过滤。"""
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

    def top_pest_regions(
        self,
        since: str,
        until: Optional[str],
        region_level: str = "city",
        top_n: int = 5,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ):
        """按区域统计虫情严重度 TopN。"""
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND monitor_time < {self._quote(until)}" if until else ""
        filter_sql = ""
        if region_level == "county" and city:
            filter_sql += f" AND city_name = {self._quote(city)}"
        if county:
            filter_sql += f" AND county_name = {self._quote(county)}"
        if region_level == "city" and city:
            filter_sql += f" AND city_name = {self._quote(city)}"
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
              {filter_sql}
            GROUP BY COALESCE({region_col}, '未知地区')
            ORDER BY severity_score DESC, record_count DESC, active_days DESC, region_name ASC
            LIMIT {int(top_n)}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def top_soil_regions(
        self,
        since: str,
        until: Optional[str],
        region_level: str = "city",
        top_n: int = 5,
        anomaly_direction: Optional[str] = None,
        city: Optional[str] = None,
        county: Optional[str] = None,
    ):
        """按区域统计墒情异常 TopN。"""
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND sample_time < {self._quote(until)}" if until else ""
        direction_sql = f"AND soil_anomaly_type = {self._quote(anomaly_direction)}" if anomaly_direction in {"low", "high"} else "AND soil_anomaly_type IN (\'low\', \'high\')"
        filter_sql = ""
        if region_level == "county" and city:
            filter_sql += f" AND city_name = {self._quote(city)}"
        if county:
            filter_sql += f" AND county_name = {self._quote(county)}"
        if region_level == "city" and city:
            filter_sql += f" AND city_name = {self._quote(city)}"
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
              {filter_sql}
            GROUP BY COALESCE({region_col}, '未知地区')
            ORDER BY anomaly_score DESC, abnormal_count DESC, region_name ASC
            LIMIT {int(top_n)}
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def pest_trend(self, since: str, until: Optional[str], region_name: str | None = None, region_level: str = "city"):
        """按天统计虫情趋势。"""
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND monitor_time < {self._quote(until)}" if until else ""
        region_sql = f"AND {region_col} = {self._quote(region_name)}" if region_name else ""
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
              {region_sql}
              AND monitor_time >= {self._quote(since)}
              {until_sql}
            GROUP BY DATE(monitor_time)
            ORDER BY day_bucket
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def soil_trend(self, since: str, until: Optional[str], region_name: str | None = None, region_level: str = "city"):
        """按天统计墒情趋势。"""
        region_col = "county_name" if region_level == "county" else "city_name"
        until_sql = f"AND sample_time < {self._quote(until)}" if until else ""
        region_sql = f"AND {region_col} = {self._quote(region_name)}" if region_name else ""
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
              {region_sql}
              AND sample_time >= {self._quote(since)}
              {until_sql}
            GROUP BY DATE(sample_time)
            ORDER BY day_bucket
          ) base
        ) q;
        """
        return self._fetch_json(sql)

    def joint_risk_regions(self, since: str, until: Optional[str], region_level: str = "city", top_n: int = 5):
        """计算虫情与低墒情的联合风险区域。"""
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
        """兼容接口：统计某时间点后的告警总数。"""
        return self._fetch_int(f"SELECT COUNT(*) FROM alerts WHERE alert_time >= {self._quote(since)};")
