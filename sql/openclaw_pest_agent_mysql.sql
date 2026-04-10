-- 说明：此 SQL 与 src/doc_ai_agent/mysql_repository.py 中的 SCHEMA_SQL 保持一致

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
