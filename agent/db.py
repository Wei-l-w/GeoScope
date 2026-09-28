"""DuckDB 访问层：连接、spatial 扩展加载、schema 抽取（供 LLM 做 schema linking）。"""

import duckdb

from . import config

# 表级业务注释：给 LLM 的"数据字典"，比裸表结构更能提升选表准确率
TABLE_COMMENTS = {
    "ais_positions": "AIS 船舶动态位置（mmsi/时间/经纬度/航速 sog 节/航向 cog）。船名船型需按 mmsi 关联 ais_ships",
    "ais_ships": "AIS 船舶静态档案（船名/船型/尺寸/目的港），主键 mmsi",
    "gdelt_events": "GDELT 全球时政事件（CAMEO 事件码/Goldstein 冲突合作分值[-10,10]/经纬度/国家）",
    "acled_events": "ACLED 冲突与政治暴力事件，含红海危机专题标注（risk_level 1-5/chokepoint 咽喉要道/fatalities）",
    "news_articles": "新闻原文，可按 related_event_id 关联 acled_events.event_id",
}

_spatial_checked = False
_spatial_ok = False


def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(config.DB_PATH, read_only=read_only)


def has_spatial(con: duckdb.DuckDBPyConnection) -> bool:
    """尝试加载 spatial 扩展（联网安装一次后离线可用）。失败时降级为纯经纬度 SQL。"""
    global _spatial_checked, _spatial_ok
    if not _spatial_checked:
        try:
            con.execute("INSTALL spatial; LOAD spatial;")
            _spatial_ok = True
        except Exception:
            _spatial_ok = False
        _spatial_checked = True
    elif _spatial_ok:
        con.execute("LOAD spatial;")
    return _spatial_ok


def list_tables(con: duckdb.DuckDBPyConnection) -> list[str]:
    return [r[0] for r in con.execute("SHOW TABLES").fetchall()]


def describe_schema(con: duckdb.DuckDBPyConnection) -> str:
    """生成给 LLM 看的 schema 文本：表注释 + 列名与类型。"""
    parts = []
    for table in list_tables(con):
        comment = TABLE_COMMENTS.get(table, "")
        cols = con.execute(f"DESCRIBE {table}").fetchall()
        col_text = ", ".join(f"{c[0]} {c[1]}" for c in cols)
        parts.append(f"表 {table}（{comment}）\n  列: {col_text}")
    return "\n\n".join(parts)


def row_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in list_tables(con)}
