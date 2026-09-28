"""GeoSQL 错题本（Vanna 思路的种子版）。

每个例题 = (自然语言问题, 参考 SQL, 关键词)。提问时按关键词重合度挑最相似的
几条例题塞进 prompt，让 LLM"仿写"，显著提升空间 SQL 准确率。
后续里程碑会把这里升级为向量检索（embedding 相似度），结构不变。

约定：
- 优先写纯经纬度 SQL（矩形框/距离公式），任何环境都能跑；
- 带 [spatial] 标记的例题用了 DuckDB spatial 扩展函数（ST_Buffer/ST_DWithin），
  仅在扩展可用时注入 prompt。
"""

EXAMPLES = [
    {
        "q": "最近一个月红海区域（北纬12-20度，东经38-46度）发生了哪些冲突事件？",
        "sql": """SELECT event_date, event_type, sub_event_type, location, fatalities, risk_level
FROM acled_events
WHERE lat BETWEEN 12 AND 20 AND lon BETWEEN 38 AND 46
  AND event_date >= CURRENT_DATE - INTERVAL 30 DAY
ORDER BY event_date DESC""",
        "keywords": ["红海", "冲突", "事件", "区域", "范围"],
    },
    {
        "q": "霍尔木兹海峡（26.5N, 56.3E）100 公里范围内有哪些高风险事件？",
        "sql": """SELECT event_date, event_type, location, risk_level, chokepoint,
       111.32 * SQRT(POW(lat - 26.5, 2) + POW((lon - 56.3) * COS(RADIANS(26.5)), 2)) AS dist_km
FROM acled_events
WHERE lat BETWEEN 25.6 AND 27.4 AND lon BETWEEN 55.4 AND 57.2
HAVING dist_km <= 100
ORDER BY dist_km""",
        "keywords": ["公里", "范围", "附近", "距离", "霍尔木兹", "海峡"],
    },
    {
        "q": "风险等级 4 以上的事件主要发生在哪些咽喉要道附近？",
        "sql": """SELECT chokepoint, COUNT(*) AS event_cnt, SUM(fatalities) AS total_fatalities,
       AVG(risk_level) AS avg_risk
FROM acled_events
WHERE risk_level >= 4 AND chokepoint IS NOT NULL
GROUP BY chokepoint
ORDER BY event_cnt DESC""",
        "keywords": ["咽喉", "要道", "风险", "统计", "排名"],
    },
    {
        "q": "MMSI 为 477123456 的船最近一周的航迹？",
        "sql": """SELECT ts, lat, lon, sog, cog
FROM ais_positions
WHERE mmsi = 477123456
  AND ts >= CURRENT_TIMESTAMP - INTERVAL 7 DAY
ORDER BY ts""",
        "keywords": ["航迹", "轨迹", "船", "mmsi", "AIS"],
    },
    {
        "q": "过去一个月经过苏伊士运河区域（29-32N, 32-33.5E）的油轮有多少艘？",
        "sql": """SELECT COUNT(DISTINCT p.mmsi) AS tanker_cnt
FROM ais_positions p
JOIN ais_ships s USING (mmsi)
WHERE p.lat BETWEEN 29 AND 32 AND p.lon BETWEEN 32 AND 33.5
  AND p.ts >= CURRENT_TIMESTAMP - INTERVAL 30 DAY
  AND s.ship_type = '油轮'""",
        "keywords": ["油轮", "苏伊士", "运河", "多少艘", "经过", "区域"],
    },
    {
        "q": "[spatial] 曼德海峡（12.6N, 43.3E）50 海里缓冲区内的事件数量？",
        "sql": """SELECT COUNT(*) AS event_cnt
FROM acled_events
WHERE ST_DWithin(
    ST_Point(lon, lat),
    ST_Point(43.3, 12.6),
    50 * 1852 / 111320.0   -- 海里转米再转度（近似）
)""",
        "keywords": ["缓冲区", "海里", "曼德", "dwithin", "buffer"],
        "needs_spatial": True,
    },
    {
        "q": "距离荷台达港（北纬14.8度，东经42.95度）最近的3起事件是哪些？",
        "sql": """SELECT location,
       111.32 * SQRT(POW(lat - 14.8, 2) + POW((lon - 42.95) * COS(RADIANS(14.8)), 2)) AS dist_km
FROM acled_events
WHERE lat IS NOT NULL AND lon IS NOT NULL
ORDER BY dist_km ASC, event_id   -- 距离相同时按主键排序，保证结果确定
LIMIT 3""",
        "keywords": ["最近", "距离", "nearest", "几起", "港口"],
    },
    {
        "q": "Goldstein 分值最低（冲突最激烈）的 10 个国家是哪些？",
        "sql": """SELECT country, COUNT(*) AS event_cnt, AVG(goldstein) AS avg_goldstein
FROM gdelt_events
WHERE goldstein IS NOT NULL AND country IS NOT NULL
GROUP BY country
HAVING COUNT(*) >= 20
ORDER BY avg_goldstein ASC
LIMIT 10""",
        "keywords": ["goldstein", "冲突", "国家", "排名", "gdelt"],
    },
    {
        "q": "某事件相关的新闻报道有哪些？",
        "sql": """SELECT n.published_at, n.source, n.title, n.url
FROM news_articles n
JOIN acled_events e ON n.related_event_id = e.event_id
WHERE e.event_id = '<事件ID>'
ORDER BY n.published_at DESC""",
        "keywords": ["新闻", "报道", "关联", "原文"],
    },
]


def retrieve(question: str, k: int = 3, spatial_ok: bool = False) -> list[dict]:
    """按关键词重合度检索最相似的 k 条例题（错题本的非向量简化版）。"""
    scored = []
    for ex in EXAMPLES:
        if ex.get("needs_spatial") and not spatial_ok:
            continue
        score = sum(1 for kw in ex["keywords"] if kw in question)
        scored.append((score, ex))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = [ex for score, ex in scored[:k] if score > 0]
    return top or [ex for _, ex in scored[:1]]  # 无命中时兜底给 1 条防格式跑偏
