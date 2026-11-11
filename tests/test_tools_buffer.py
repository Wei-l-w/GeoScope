"""buffer_analysis 的返回值：总数之后附按类型计数，路径仍在末尾、能被提取（不连真实仓库）。"""

from contextlib import contextmanager

import pytest

from agent import artifacts, tools


def _rows(*types):
    # (event_date, event_type, location, lat, lon, dist_km)：都在 150 km 圈内
    return [("2023-12-01", event_type, "Bab el-Mandeb", 12.6, 43.3, 10.0) for event_type in types]


@pytest.fixture
def warehouse(monkeypatch):
    def serve(rows):
        class _Con:
            def execute(self, sql):
                return self

            def fetchall(self):
                return rows

        @contextmanager
        def connect(*args, **kwargs):
            yield _Con()

        monkeypatch.setattr(tools.db, "connect", connect)
    return serve


def _run(**kwargs):
    return tools.buffer_analysis.invoke({"lat": 12.58, "lon": 43.33, "radius_km": 150, **kwargs})


def test_counts_by_type_come_before_the_saved_path(warehouse):
    warehouse(_rows("Battles", "Protests", "Battles", "Explosions/Remote violence", "Battles",
                    "Explosions/Remote violence"))
    out = _run()
    assert ("圈内共 6 条记录（acled_events）。按类型：Battles 3、Explosions/Remote violence 2、Protests 1。"
            "GeoJSON 已保存：") in out
    assert artifacts.extract_tool_path(out).endswith(".geojson")


def test_gdelt_types_beyond_the_top_eight_are_merged(warehouse):
    # GDELT 的 event_code 列存的是事件名称，名称里常带逗号和空格。
    # Threaten 与 "Arrest, detain" 同为 2 条、卡在第 8 名：Threaten 先返回，但同数按名称排，第 8 名是后者。
    counts = {"Consult, not specified below": 10, "Make statement": 9, "Host a visit": 8, "Praise or endorse": 7,
              "Express intent to meet or negotiate": 6, "Make an appeal or request": 5, "Accuse": 4,
              "Threaten": 2, "Arrest, detain": 2, "Demand": 1}
    warehouse(_rows(*[name for name, count in counts.items() for _ in range(count)]))
    out = _run(table="gdelt_events")
    assert ("圈内共 54 条记录（gdelt_events）。按类型：Consult, not specified below 10、Make statement 9、"
            "Host a visit 8、Praise or endorse 7、Express intent to meet or negotiate 6、"
            "Make an appeal or request 5、Accuse 4、Arrest, detain 2、其余 2 类共 3 条。GeoJSON 已保存：") in out


def test_missing_or_blank_types_are_counted_as_unknown(warehouse):
    warehouse(_rows("Battles", None, ""))
    assert "按类型：未知 2、Battles 1。" in _run()


def test_an_empty_buffer_has_no_breakdown(warehouse):
    warehouse([])
    assert "圈内共 0 条记录（acled_events）。GeoJSON 已保存：" in _run()


def test_truncated_query_points_keep_a_parseable_path(monkeypatch):
    """点数超过上图上限时的提示不能接在路径那一行，否则路径被解析成"…geojson（仅前…）"。"""
    from agent.geosql import GeoSQLResult

    monkeypatch.setattr(tools, "_MAX_GEO_POINTS", 2)
    result = GeoSQLResult("q", columns=["lat", "lon", "name"],
                          rows=[(12.0 + i, 43.0, f"p{i}") for i in range(3)])
    note = tools._rows_to_geojson(result)
    assert "仅前 2 个点上图" in note
    path = artifacts.extract_tool_path(note)
    assert path.endswith(".geojson")
    assert artifacts.validated_path(path) == path
