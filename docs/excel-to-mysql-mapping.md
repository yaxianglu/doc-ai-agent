# Excel 到 MySQL 表结构映射

这份文档说明当前 `doc-ai-agent` 在设计 MySQL 表结构时，是如何与 Excel 原始表对应的。

目标不是描述“最终问答怎么查”，而是描述：

- 原始 Excel 来自哪里
- 每个 Excel 对应哪些 MySQL 表
- 字段是直接映射、清洗后映射，还是推导后写入
- 哪些维度信息来自补充表，而不是来自原始监测表

## 1. 当前数据源

当前导入链路主要使用三类 Excel：

1. `虫情.xlsx`
2. `墒情.xlsx`
3. `处置建议发布任务.xlsx`

其中：

- `虫情.xlsx` 和 `墒情.xlsx` 是主监测数据
- `处置建议发布任务.xlsx` 既写入 `alerts`，也补充设备与区域映射信息

## 2. 对应的 MySQL 表

当前 MySQL 侧的核心表有：

- `etl_import_batch`：导入批次表
- `dim_region`：区域维表
- `dim_device`：设备维表
- `alerts`：告警事实表
- `fact_pest_monitor`：虫情事实表
- `fact_soil_moisture`：墒情事实表
- `metric_rule`：分析规则表

其中与 Excel 直接相关的重点是：

- `虫情.xlsx` -> `fact_pest_monitor`
- `墒情.xlsx` -> `fact_soil_moisture`
- `处置建议发布任务.xlsx` -> `alerts`
- `虫情.xlsx`、`处置建议发布任务.xlsx` -> `dim_region` / `dim_device`

## 3. 总体导入流程

### 3.1 虫情

- 扫描 `虫情.xlsx`
- 逐行解析为虫情监测记录
- 写入 `fact_pest_monitor`
- 同时从行内的城市、区县、设备信息补充：
  - `dim_region`
  - `dim_device`

### 3.2 墒情

- 扫描 `墒情.xlsx`
- 逐行解析为墒情监测记录
- 写入 `fact_soil_moisture`
- 由于墒情表本身不带完整的市/县/设备名称等字段，所以这些维度信息不是直接来自 `墒情.xlsx`
- 墒情数据写入后，再通过 `device_sn` 与 `dim_device` 关联，回填：
  - `city_name`
  - `county_name`
  - `town_name`
  - `device_name`
  - `longitude`
  - `latitude`

### 3.3 处置建议发布任务

- 逐行解析为告警记录
- 写入 `alerts`
- 对于告警类型为 `土壤墒情仪` 的记录，还会抽取设备与区域映射，写入：
  - `dim_region`
  - `dim_device`

因此，**墒情表的区域归属，实际上依赖补充表里的设备映射信息**。

## 4. `虫情.xlsx` -> `fact_pest_monitor`

### 4.1 原始表头

当前 `虫情.xlsx` 第一张表表头为：

- `id`
- `device_name`
- `device_type`
- `device_status`
- `sn`
- `city`
- `country`
- `lon`
- `lat`
- `pest_name`
- `pest_num`
- `monitor_time`
- `create_time`

### 4.2 字段映射

| Excel 字段 | MySQL 字段 | 说明 |
| --- | --- | --- |
| `id` | `record_id` | 直接映射，作为虫情记录主键 |
| 导入批次 | `batch_id` | 非 Excel 字段，导入时生成 |
| `sn` | `device_sn` | 直接映射 |
| `device_name` | `device_name` | 直接映射 |
| `device_type` | `device_type` | 直接映射 |
| `device_status` | `device_status` | 直接映射 |
| `city` | `city_name` | 直接映射 |
| `country` | `county_name` | 直接映射，字段名虽叫 `country`，实际承载区县 |
| `lon` | `longitude` | 转浮点 |
| `lat` | `latitude` | 转浮点 |
| `pest_name` | `pest_name_raw` | 保留原始值 |
| `pest_num` | `pest_num_raw` | 保留原始值 |
| `pest_name` | `normalized_pest_names` | 逗号拆分并标准化后拼接 |
| `pest_num` | `normalized_pest_count` | 逗号拆分后求和，异常值剔除 |
| `pest_num` 推导 | `severity_usable` | 能否参与严重度分析 |
| 多字段推导 | `data_quality_flag` | 如虫种无效、数量异常、缺少经纬度等 |
| `monitor_time` | `monitor_time` | Excel 序列日期转 `YYYY-MM-DD HH:MM:SS` |
| `create_time` | `create_time` | Excel 序列日期转 `YYYY-MM-DD HH:MM:SS` |
| 文件名 | `source_file` | 非 Excel 字段，导入时补充 |
| sheet 名 | `source_sheet` | 非 Excel 字段，导入时补充 |
| 行号 | `source_row` | 非 Excel 字段，导入时补充 |

### 4.3 同步补充维表

`虫情.xlsx` 还会直接补充：

- `dim_region`
  - `province_name`
  - `city_name`
  - `county_name`
  - `town_name`
  - `region_key`
- `dim_device`
  - `device_sn`
  - `device_name`
  - `device_type`
  - `city_name`
  - `county_name`
  - `longitude`
  - `latitude`
  - `mapping_source = 虫情.xlsx`
  - `mapping_confidence = native_pest`

## 5. `墒情.xlsx` -> `fact_soil_moisture`

### 5.1 原始表头

当前 `墒情.xlsx` 第一张表表头为：

- `id`
- `sn`
- `gatewayid`
- `sensorid`
- `unitid`
- `time`
- `water20cm`
- `water40cm`
- `water60cm`
- `water80cm`
- `t20cm`
- `t40cm`
- `t60cm`
- `t80cm`
- `water20cmfieldstate`
- `water40cmfieldstate`
- `water60cmfieldstate`
- `water80cmfieldstate`
- `t20cmfieldstate`
- `t40cmfieldstate`
- `t60cmfieldstate`
- `t80cmfieldstate`
- `create_time`

### 5.2 字段映射

| Excel 字段 | MySQL 字段 | 说明 |
| --- | --- | --- |
| `id` | `record_id` | 直接映射，作为墒情记录主键 |
| 导入批次 | `batch_id` | 非 Excel 字段，导入时生成 |
| `sn` | `device_sn` | 直接映射 |
| `gatewayid` | `gateway_id` | 直接映射 |
| `sensorid` | `sensor_id` | 直接映射 |
| `unitid` | `unit_id` | 直接映射 |
| `time` | `sample_time` | Excel 序列日期转时间 |
| `create_time` | `create_time` | Excel 序列日期转时间 |
| `water20cm` | `water20cm` | 转浮点 |
| `water40cm` | `water40cm` | 转浮点 |
| `water60cm` | `water60cm` | 转浮点 |
| `water80cm` | `water80cm` | 转浮点 |
| `t20cm` | `t20cm` | 转浮点 |
| `t40cm` | `t40cm` | 转浮点 |
| `t60cm` | `t60cm` | 转浮点 |
| `t80cm` | `t80cm` | 转浮点 |
| `water20cmfieldstate` | `water20cm_field_state` | 直接映射 |
| `water40cmfieldstate` | `water40cm_field_state` | 直接映射 |
| `water60cmfieldstate` | `water60cm_field_state` | 直接映射 |
| `water80cmfieldstate` | `water80cm_field_state` | 直接映射 |
| `t20cmfieldstate` | `t20cm_field_state` | 直接映射 |
| `t40cmfieldstate` | `t40cm_field_state` | 直接映射 |
| `t60cmfieldstate` | `t60cm_field_state` | 直接映射 |
| `t80cmfieldstate` | `t80cm_field_state` | 直接映射 |
| `water20cm` 推导 | `water20cm_valid` | 0~300 视为有效 |
| `t20cm` 推导 | `t20cm_valid` | -30~60 视为有效 |
| `water20cm` 推导 | `soil_anomaly_type` | `<50 -> low`，`>150 -> high`，否则 `normal` |
| `water20cm` 推导 | `soil_anomaly_score` | `<50 -> 50-x`，`>150 -> x-150` |
| `water20cm`、`t20cm` 推导 | `data_quality_flag` | 缺失或越界则打标 |
| 文件名 | `source_file` | 非 Excel 字段，导入时补充 |
| sheet 名 | `source_sheet` | 非 Excel 字段，导入时补充 |
| 行号 | `source_row` | 非 Excel 字段，导入时补充 |

### 5.3 不是来自 `墒情.xlsx` 的字段

以下字段虽然最终存在于 `fact_soil_moisture` 中，但**不是直接从 `墒情.xlsx` 来的**：

- `city_name`
- `county_name`
- `town_name`
- `device_name`
- `longitude`
- `latitude`

这几个字段在初次写入 `fact_soil_moisture` 时通常为空，之后通过：

- `fact_soil_moisture.device_sn`
- 关联 `dim_device.device_sn`

再由 `enrich_soil_dimensions()` 回填。

因此，**墒情事实表是“监测值来自墒情表，区域设备维度来自设备维表”的二阶段建模**。

## 6. `处置建议发布任务.xlsx` -> `alerts`

### 6.1 原始表头

当前告警补充表第一张表表头为：

- `告警内容`
- `告警类型(预警信号,虫情,土壤)`
- `告警子类型`
- `告警时间`
- `告警等级`
- `区域编码`
- `区域名称`
- `告警值`
- `设备编码`
- `设备名称`
- `经度`
- `维度`
- `设备所在市`
- `设备所在区县`
- `短信内容`
- `处置建议`

### 6.2 字段映射

| Excel 字段 | MySQL 字段 | 说明 |
| --- | --- | --- |
| `告警内容` | `alert_content` | 直接映射 |
| `告警类型(预警信号,虫情,土壤)` | `alert_type` | 直接映射 |
| `告警子类型` | `alert_subtype` | 直接映射 |
| `告警时间` | `alert_time` | Excel 序列日期转时间 |
| `告警等级` | `alert_level` | 直接映射 |
| `区域编码` | `region_code` | 直接映射 |
| `区域名称` | `region_name` | 直接映射 |
| `告警值` | `alert_value` | 直接映射 |
| `设备编码` | `device_code` | 直接映射 |
| `设备名称` | `device_name` | 直接映射 |
| `经度` | `longitude` | 直接映射 |
| `维度` | `latitude` | 直接映射，Excel 原字段名是“维度” |
| `设备所在市` | `city` | 直接映射 |
| `设备所在区县` | `county` | 直接映射 |
| `短信内容` | `sms_content` | 直接映射 |
| `处置建议` | `disposal_suggestion` | 直接映射 |
| 文件名 | `source_file` | 非 Excel 字段，导入时补充 |
| sheet 名 | `source_sheet` | 非 Excel 字段，导入时补充 |
| 行号 | `source_row` | 非 Excel 字段，导入时补充 |

### 6.3 对 `dim_region` / `dim_device` 的补充作用

当告警类型为 `土壤墒情仪` 时，这张表还会被用来抽取设备映射，写入：

- `dim_device`
  - `device_sn`
  - `device_name`
  - `device_type`
  - `city_name`
  - `county_name`
  - `town_name`
  - `longitude`
  - `latitude`
  - `mapping_source = 处置建议发布任务.xlsx`
  - `mapping_confidence = alert_enrichment`

同时也会补到 `dim_region`。

这一步的意义是：

- `墒情.xlsx` 有 `device_sn` 和监测值
- 告警补充表有 `device_sn` 对应的地区与设备名称
- 最终通过 `dim_device` 把两边接起来

## 7. 为什么表结构不是完全按 Excel 原样设计

当前 MySQL 结构不是简单“一张 Excel 对应一张一模一样的表”，而是做了建模拆分：

### 7.1 事实表与维表分离

- 监测值放事实表：
  - `fact_pest_monitor`
  - `fact_soil_moisture`
  - `alerts`
- 区域和设备放维表：
  - `dim_region`
  - `dim_device`

这样做的目的是：

- 避免同一个设备信息在每条记录里重复维护
- 便于后续做区域聚合、设备分析、维度补全
- 支持墒情表这种“监测数据与区域映射不在同一张 Excel” 的情况

### 7.2 保留原始值 + 派生分析值

例如：

- 虫情：
  - 保留 `pest_name_raw`、`pest_num_raw`
  - 同时计算 `normalized_pest_names`、`normalized_pest_count`
- 墒情：
  - 保留原始含水量和温度
  - 同时计算 `soil_anomaly_type`、`soil_anomaly_score`

这样既方便追溯原始数据，也方便分析查询直接使用。

## 8. 当前设计的一个重要现实约束

当前设计里，**墒情数据的“区域归属”并不是纯粹由 `墒情.xlsx` 决定的**。

它依赖：

1. `墒情.xlsx` 提供 `device_sn`
2. `处置建议发布任务.xlsx` 或其他来源补充该 `device_sn` 的市/县/设备信息
3. `enrich_soil_dimensions()` 再把这些维度回填到 `fact_soil_moisture`

这也是为什么会出现：

- `未知地区`
- 区县字段为空
- 某些设备无法正确落到县级区域

本质上这不是问答层的问题，而是**导入建模依赖“设备映射是否完整”**。

## 9. 代码落点

如果后续你要追代码，最关键的是这几处：

- 导入流程入口：`src/doc_ai_agent/server.py`
- MySQL 表结构：`src/doc_ai_agent/mysql_repository.py`
- 虫情行解析：`src/doc_ai_agent/pest_loader.py`
- 墒情行解析：`src/doc_ai_agent/soil_loader.py`
- 告警表解析：`src/doc_ai_agent/xlsx_loader.py`
- 通用 Excel 读取：`src/doc_ai_agent/xlsx_utils.py`

## 10. 一句话总结

当前这套设计不是“Excel 原样落库”，而是：

- **虫情**：原始监测表直接入事实表，同时补设备/区域维表
- **墒情**：原始监测值入事实表，设备与区域维度依赖补充表回填
- **告警补充表**：既入 `alerts`，又承担设备区域映射补全职责

因此，Excel 与 MySQL 的关系是：

- **一部分字段直接映射**
- **一部分字段清洗后映射**
- **一部分字段由规则推导**
- **一部分字段通过其他 Excel 的设备映射二次补全**
