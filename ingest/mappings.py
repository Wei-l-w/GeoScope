"""字段映射配置：真实数据格式与标准表对齐时只需要改这个文件。

每个数据源的配置说明：
- table:        目标表名（见 db/schema.sql）
- key:          去重主键（重复导入同一文件不会产生重复行）
- columns:      {标准字段: SQL 表达式}，表达式可为列名或任意 DuckDB SQL（可做单位换算）
- geo:          是否含经纬度（入库时自动过滤非法坐标）
- read_options: CSV 读取选项（分隔符、无表头时的列名等），省略则自动推断

当前配置对应的源数据格式（真实数据文件不随仓库分发，放在本地任意路径即可）：
- ais        AIS 动态位置 CSV：~ 分隔、无表头、12 列
- ais_static AIS 静态档案 CSV：~ 分隔、无表头、17 列
- gdelt      GDELT 标准导出 CSV（额外带 EventName / country_name 增强列）
- acled      ACLED 官方字段 CSV + 红海危机专题 LLM 标注列
- news       新闻正文抓取结果 JSONL（按 event_id_cnty 关联 ACLED 事件）
"""

# AIS 船舶类型码 -> 中文（ITU 标准类型码段）
_AIS_TYPE_CASE = """
CASE
    WHEN "ShipType" IS NULL THEN NULL
    WHEN "ShipType" = 30 THEN '渔船'
    WHEN "ShipType" IN (31, 32) THEN '拖带作业船'
    WHEN "ShipType" = 35 THEN '军用船'
    WHEN "ShipType" = 36 THEN '帆船'
    WHEN "ShipType" = 37 THEN '游艇'
    WHEN "ShipType" BETWEEN 40 AND 49 THEN '高速船'
    WHEN "ShipType" = 50 THEN '引航船'
    WHEN "ShipType" = 51 THEN '搜救船'
    WHEN "ShipType" = 52 THEN '拖轮'
    WHEN "ShipType" = 55 THEN '执法船'
    WHEN "ShipType" BETWEEN 60 AND 69 THEN '客船'
    WHEN "ShipType" BETWEEN 70 AND 79 THEN '货船'
    WHEN "ShipType" BETWEEN 80 AND 89 THEN '油轮'
    WHEN "ShipType" BETWEEN 90 AND 99 THEN '其他船舶'
    ELSE '未知(' || CAST("ShipType" AS VARCHAR) || ')'
END
"""

MAPPINGS = {
    # ---- AIS 动态位置：~ 分隔无表头 ----
    # 原始单位：经纬度 1/600000 度，航速/航向 0.1 单位，时间 UTC 秒
    "ais": {
        "table": "ais_positions",
        "key": ["mmsi", "ts"],
        "geo": True,
        "read_options": {
            "delim": "~",
            "header": False,
            "names": ["MMSI", "ROT", "ClassType", "PosTime", "Lon", "Lat", "Course",
                      "TrueHeading", "Speed", "NavigationStatus", "Accuracy", "ReceiveTime"],
        },
        "columns": {
            "mmsi": '"MMSI"',
            "ts": 'to_timestamp("PosTime")',
            "lat": '"Lat" / 600000.0',
            "lon": '"Lon" / 600000.0',
            "sog": 'CASE WHEN "Speed" >= 1022 THEN NULL ELSE "Speed" / 10.0 END',
            "cog": 'CASE WHEN "Course" >= 3600 THEN NULL ELSE "Course" / 10.0 END',
            "heading": 'CASE WHEN "TrueHeading" >= 511 THEN NULL ELSE "TrueHeading" END',
            "ship_name": "NULL",   # 船名/类型来自静态表 ais_ships，按 mmsi 关联
            "ship_type": "NULL",
        },
    },
    # ---- AIS 静态档案：~ 分隔无表头 ----
    "ais_static": {
        "table": "ais_ships",
        "key": ["mmsi"],
        "geo": False,
        "read_options": {
            "delim": "~",
            "header": False,
            "names": ["MMSI", "IMO", "Callsign", "ShipName", "ShipType", "Length",
                      "Breadth", "pos_fixing_device", "ETA", "Draught", "Destination",
                      "ClassType", "ReceiveTime", "to_bow", "to_stern", "to_port", "to_starboard"],
        },
        "columns": {
            "mmsi": '"MMSI"',
            "imo": 'NULLIF("IMO", 0)',
            "callsign": 'NULLIF(TRIM("Callsign"), \'\')',
            "ship_name": 'NULLIF(TRIM("ShipName"), \'\')',
            "ship_type": _AIS_TYPE_CASE,
            "type_code": '"ShipType"',
            "length_m": 'NULLIF("Length", 0)',
            "breadth_m": 'NULLIF("Breadth", 0)',
            "draught_m": 'NULLIF("Draught", 0) / 10.0',
            "destination": 'NULLIF(TRIM("Destination"), \'\')',
            "updated_at": 'to_timestamp("ReceiveTime")',
        },
    },
    # ---- GDELT：标准列名 + 中文增强列（EventName / 国家名） ----
    "gdelt": {
        "table": "gdelt_events",
        "key": ["event_id"],
        "geo": True,
        "columns": {
            "event_id": '"GLOBALEVENTID"',
            "event_date": "STRPTIME(CAST(CAST(\"SQLDATE\" AS BIGINT) AS VARCHAR), '%Y%m%d')",
            "actor1": '"Actor1Name"',
            "actor2": '"Actor2Name"',
            # 该数据带 EventName（CAMEO 代码的可读名称），优先使用
            "event_code": 'COALESCE("EventName", CAST("EventCode" AS VARCHAR))',
            "goldstein": '"GoldsteinScale"',
            "avg_tone": '"AvgTone"',
            "lat": '"ActionGeo_Lat"',
            "lon": '"ActionGeo_Long"',
            "country": 'COALESCE("ActionGeo_CountryName", "country_name", "ActionGeo_CountryCode")',
            "num_mentions": '"NumMentions"',
            "source_url": '"SOURCEURL"',
        },
    },
    # ---- ACLED：红海危机 LLM 筛选增强版（v3_enriched，含专题标注字段） ----
    "acled": {
        "table": "acled_events",
        "key": ["event_id"],
        "geo": True,
        "columns": {
            "event_id": '"event_id_cnty"',
            "event_date": '"event_date"',
            "event_type": '"event_type"',
            "sub_event_type": '"sub_event_type"',
            "actor1": '"actor1"',
            "actor2": '"actor2"',
            "country": '"country"',
            "admin1": '"admin1"',
            "location": '"location"',
            "lat": '"latitude"',
            "lon": '"longitude"',
            "fatalities": '"fatalities"',
            "notes": '"notes"',
            "phase": '"phase"',
            "risk_level": '"risk_level_v2"',
            "target_class": 'NULLIF("target_class_v2", \'unknown\')',
            "causal_role": '"causal_role_in_crisis"',
            "ais_tier": '"ais_relevance_tier_v2"',
            "actor_role": '"actor_role"',
            "domain": '"domain"',
            "is_kinetic": '"is_kinetic"',
            "chokepoint": '"nearest_chokepoint"',
            "chokepoint_km": '"nearest_chokepoint_km"',
            "nearest_port": '"nearest_port"',
            "port_km": '"nearest_port_km"',
        },
    },
    # ---- 新闻原文：ACLED 原文回填 JSONL（仅收录抓取成功且有标题的文章） ----
    "news": {
        "table": "news_articles",
        "key": ["id"],
        "geo": False,
        "columns": {
            # 抓取失败的行 id 为 NULL，自动被过滤；按 URL 去重
            "id": "CASE WHEN status_code = 200 AND title IS NOT NULL "
                  "THEN md5(COALESCE(final_url, url)) END",
            # 网页解析的日期偶有脏值（如 1997/2026），限定在危机窗口附近才采信
            "published_at": "CASE WHEN TRY_CAST(\"published_date\" AS DATE) "
                            "BETWEEN DATE '2023-01-01' AND DATE '2024-06-30' "
                            "THEN TRY_CAST(\"published_date\" AS TIMESTAMP) END",
            # 用文章 URL 域名作为来源（原 source 字段是 ACLED 事件的多来源拼接串）
            "source": "regexp_extract(COALESCE(\"final_url\", \"url\"), "
                      "'https?://(?:www\\.)?([^/]+)', 1)",
            "title": '"title"',
            "body": 'COALESCE("text_preview", \'\')',
            "url": 'COALESCE("final_url", "url")',
            "lang": "'en'",
            "related_event_id": '"event_id_cnty"',
        },
    },
}
