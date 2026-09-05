-- 数据仓库标准表结构
-- 所有数据源经 ingest/ 脚本标准化后写入以下四张表

CREATE TABLE IF NOT EXISTS ais_positions (
    mmsi       BIGINT,          -- 船舶唯一标识
    ts         TIMESTAMP,       -- 位置上报时间
    lat        DOUBLE,
    lon        DOUBLE,
    sog        DOUBLE,          -- 对地航速 (节)
    cog        DOUBLE,          -- 对地航向 (度)
    heading    DOUBLE,          -- 船首向 (度)
    ship_name  VARCHAR,
    ship_type  VARCHAR
);

-- AIS 船舶静态档案（船名/类型/尺寸，与动态位置按 mmsi 关联）
CREATE TABLE IF NOT EXISTS ais_ships (
    mmsi         BIGINT,
    imo          BIGINT,
    callsign     VARCHAR,
    ship_name    VARCHAR,
    ship_type    VARCHAR,        -- 类型码翻译后的文字
    type_code    INTEGER,        -- AIS 原始类型码
    length_m     DOUBLE,
    breadth_m    DOUBLE,
    draught_m    DOUBLE,
    destination  VARCHAR,
    updated_at   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gdelt_events (
    event_id     BIGINT,
    event_date   DATE,
    actor1       VARCHAR,
    actor2       VARCHAR,
    event_code   VARCHAR,       -- CAMEO 事件代码
    goldstein    DOUBLE,        -- Goldstein 冲突/合作分值 [-10, 10]
    avg_tone     DOUBLE,        -- 报道平均语调
    lat          DOUBLE,
    lon          DOUBLE,
    country      VARCHAR,
    num_mentions INTEGER,
    source_url   VARCHAR
);

CREATE TABLE IF NOT EXISTS acled_events (
    event_id       VARCHAR,
    event_date     DATE,
    event_type     VARCHAR,
    sub_event_type VARCHAR,
    actor1         VARCHAR,
    actor2         VARCHAR,
    country        VARCHAR,
    admin1         VARCHAR,
    location       VARCHAR,
    lat            DOUBLE,
    lon            DOUBLE,
    fatalities     INTEGER,
    notes          VARCHAR,
    -- ---- 红海危机专题标注字段（来自 LLM 筛选增强版）----
    phase          VARCHAR,      -- 危机阶段: precursor / trigger_chain / maritime_crisis
    risk_level     INTEGER,      -- 风险等级 1-5
    target_class   VARCHAR,      -- 目标类型: vessel / military_base / oil_facility / ...
    causal_role    VARCHAR,      -- 危机因果角色: direct_maritime_attack / regional_escalation / ...
    ais_tier       VARCHAR,      -- 与 AIS 关联层级: tier_A_direct / tier_B_signal / tier_C_context
    actor_role     VARCHAR,      -- 行为方角色: resistance_axis / state_force / coalition_response / ...
    domain         VARCHAR,      -- 事件域: land / air / maritime
    is_kinetic     BOOLEAN,      -- 是否动能事件
    chokepoint     VARCHAR,      -- 最近咽喉要道
    chokepoint_km  DOUBLE,       -- 距咽喉要道公里数
    nearest_port   VARCHAR,      -- 最近港口
    port_km        DOUBLE        -- 距港口公里数
);

CREATE TABLE IF NOT EXISTS news_articles (
    id               VARCHAR,
    published_at     TIMESTAMP,
    source           VARCHAR,
    title            VARCHAR,
    body             VARCHAR,
    url              VARCHAR,
    lang             VARCHAR,
    related_event_id VARCHAR      -- 关联的 ACLED 事件 ID（可为空）
);
