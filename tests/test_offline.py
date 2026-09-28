"""离线单元测试：不依赖 LLM，CI 可跑。

依赖数据仓库：CI 中由样例数据生成器构建（WAREHOUSE_PATH 环境变量指向）。
本地跑：pytest tests/ -q（默认用 data/warehouse.duckdb）
"""

import json

import pytest

from agent import db, fewshot, geosql, rag
from agent.tools import buffer_analysis, ship_track, _circle_polygon, _rows_to_geojson


# ---------------- 数据访问层 ----------------

def test_tables_exist():
    with db.connect() as con:
        tables = set(db.list_tables(con))
    assert {"ais_positions", "ais_ships", "gdelt_events", "acled_events", "news_articles"} <= tables


def test_describe_schema_contains_columns():
    with db.connect() as con:
        schema = db.describe_schema(con)
    assert "ais_positions" in schema
    assert "mmsi" in schema and "lat" in schema
    assert "ACLED" in schema  # 业务数据字典注释


# ---------------- 错题本检索 ----------------

def test_fewshot_retrieve_distance():
    hits = fewshot.retrieve("霍尔木兹海峡100公里范围内有哪些事件", k=2, spatial_ok=False)
    assert hits, "应至少命中一条例题"
    assert any("SQRT" in h["sql"] for h in hits), "距离类问题应命中距离公式例题"


def test_fewshot_spatial_gating():
    q = "曼德海峡50海里缓冲区"
    without = fewshot.retrieve(q, k=5, spatial_ok=False)
    with_ = fewshot.retrieve(q, k=5, spatial_ok=True)
    assert all(not h.get("needs_spatial") for h in without), "spatial 不可用时不得注入 ST_ 例题"
    assert any(h.get("needs_spatial") for h in with_), "spatial 可用时应能命中 ST_ 例题"


def test_fewshot_fallback_nonempty():
    # 完全无关键词命中时也应兜底返回，防止 prompt 格式跑偏
    assert fewshot.retrieve("随便说点什么", k=3, spatial_ok=False)


# ---------------- SQL 抽取 ----------------

@pytest.mark.parametrize("text,expect", [
    ("```sql\nSELECT 1;\n```", "SELECT 1"),
    ("  SELECT count(*) FROM t  ", "SELECT count(*) FROM t"),
    ("前置废话\n```SQL\nselect a from b\n```\n后置废话", "select a from b"),
])
def test_extract_sql_ok(text, expect):
    assert geosql._extract_sql(text) == expect


def test_extract_sql_reject_non_select():
    with pytest.raises(ValueError):
        geosql._extract_sql("DROP TABLE ais_positions")


# ---------------- GIS 工具 ----------------

def test_circle_polygon_closed():
    coords = _circle_polygon(15.0, 42.0, 100, n=16)[0]
    assert len(coords) == 17 and coords[0] == coords[-1], "圆多边形必须闭合"


def test_buffer_analysis_on_sample():
    out = json.loads("{}") if False else buffer_analysis.invoke(
        {"lat": 15.0, "lon": 41.5, "radius_km": 500, "table": "acled_events"}
    )
    assert "圈内共" in out and "GeoJSON 已保存" in out


def test_ship_track_unknown_mmsi():
    out = ship_track.invoke({"mmsi": 999999999, "days": 30})
    assert "未找到" in out


# ---------------- 查询结果上图 ----------------

class _FakeResult:
    def __init__(self, columns, rows):
        self.columns, self.rows = columns, rows


def test_rows_to_geojson_with_coords(tmp_path):
    r = _FakeResult(
        ["location", "lat", "lon", "fatalities"],
        [("荷台达", 14.8, 42.95, 3), ("无坐标点", None, None, 1)],
    )
    out = _rows_to_geojson(r)
    assert out and "GeoJSON 已保存：" in out
    path = out.split("GeoJSON 已保存：")[1].strip().splitlines()[0]
    data = json.loads(open(path, encoding="utf-8").read())
    assert len(data["features"]) == 1, "空坐标行应被过滤"
    feat = data["features"][0]
    assert feat["geometry"]["coordinates"] == [42.95, 14.8]
    assert feat["properties"]["location"] == "荷台达"
    assert "lat" not in feat["properties"], "坐标列不应重复出现在属性里"


def test_rows_to_geojson_without_coords():
    r = _FakeResult(["event_type", "cnt"], [("Battles", 56)])
    assert _rows_to_geojson(r) is None


# ---------------- 会话持久化 ----------------

@pytest.fixture()
def temp_sessions_db(tmp_path, monkeypatch):
    import agent.sessions as sm
    monkeypatch.setattr(sm, "DB_PATH", tmp_path / "sessions.duckdb")
    return sm


def test_sessions_crud(temp_sessions_db):
    sm = temp_sessions_db
    sid = sm.create_session("曼德海峡分析")
    sm.save_message(sid, "user", "曼德海峡在哪？")
    sm.save_message(sid, "assistant", "位于也门与吉布提之间", steps=["geocode(...)"], geojson=["/tmp/a.geojson"])

    sessions = sm.list_sessions()
    assert len(sessions) == 1 and sessions[0][0] == sid and sessions[0][3] == 2

    msgs = sm.load_messages(sid)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["steps"] == ["geocode(...)"]
    assert msgs[1]["geojson"] == ["/tmp/a.geojson"]

    sm.delete_session(sid)
    assert sm.list_sessions() == []


def test_sessions_empty_db(temp_sessions_db):
    assert temp_sessions_db.list_sessions() == []


# ---------------- RAG ----------------

def test_split_text_overlap():
    text = "第一句。" * 200
    chunks = rag._split_text(text)
    assert len(chunks) > 1
    assert all(len(c) <= rag._CHUNK_SIZE for c in chunks)


def test_rag_search_if_corpus():
    try:
        hits = rag.search("Houthi attack", k=3)
    except RuntimeError:
        pytest.skip("语料为空（样例数据无新闻正文）")
    assert hits and hits[0][1] >= rag._MIN_SCORE
