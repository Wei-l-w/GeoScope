"""航迹回归：只读临时 DuckDB，GeoJSON 也写入临时目录，不调用模型。"""

import json

import duckdb
import pytest

from agent import tools


MMSI = 123456789


@pytest.fixture
def track_store(tmp_path, monkeypatch):
    database = tmp_path / "tracks.duckdb"
    with duckdb.connect(str(database)) as con:
        con.execute(
            "CREATE TABLE ais_positions "
            "(mmsi BIGINT, ts TIMESTAMP, lat DOUBLE, lon DOUBLE, sog DOUBLE)"
        )
    monkeypatch.setattr(tools.db, "connect", lambda: duckdb.connect(str(database), read_only=True))
    monkeypatch.setattr(tools, "OUTPUT_DIR", tmp_path / "geojson")
    return database


def _read_feature(output):
    path = output.split("GeoJSON 已保存：", 1)[1]
    with open(path, encoding="utf-8") as stream:
        result = json.load(stream)
    assert result["type"] == "FeatureCollection"
    assert len(result["features"]) == 1
    return result["features"][0]


@pytest.mark.parametrize("count", [0, 1, 2, 499, 500, 501, 999, 1499, 40001])
def test_track_size_order_and_endpoints(track_store, count):
    with duckdb.connect(str(track_store)) as con:
        # 倒序落盘，验证输出顺序来自时间排序而非物理存储顺序。
        con.execute(
            "INSERT INTO ais_positions "
            "SELECT ?, TIMESTAMP '2024-01-01' + i * INTERVAL '1 second', "
            "10.0, -100.0 + i / 1000.0, 5.0 "
            "FROM range(?) AS samples(i) ORDER BY i DESC",
            [MMSI, count],
        )
    output = tools.ship_track.invoke({"mmsi": MMSI, "days": 7})
    assert "仓库最新时间" in output
    if not count:
        assert "未找到" in output
        assert not tools.OUTPUT_DIR.exists()
        return

    feature = _read_feature(output)
    properties = feature["properties"]
    geometry = feature["geometry"]
    assert properties["points_total"] == count
    assert properties["points_shown"] == min(count, 500)
    if count == 1:
        assert geometry == {"type": "Point", "coordinates": [-100.0, 10.0]}
    else:
        assert geometry["type"] == "LineString"
        coordinates = geometry["coordinates"]
        assert len(coordinates) == min(count, 500)
        assert coordinates[0] == [-100.0, 10.0]
        assert coordinates[-1] == pytest.approx([-100.0 + (count - 1) / 1000.0, 10.0])
        assert all(a[0] < b[0] for a, b in zip(coordinates, coordinates[1:]))
        assert len({tuple(coordinate) for coordinate in coordinates}) == len(coordinates)


@pytest.mark.parametrize("with_valid", [False, True])
def test_track_filters_null_nonfinite_and_out_of_range_coordinates(track_store, with_valid):
    invalid = [
        (None, 20.0), (20.0, None), (None, None),
        (float("nan"), 20.0), (20.0, float("nan")),
        (float("inf"), 20.0), (20.0, float("-inf")),
        (90.1, 20.0), (-90.1, 20.0), (20.0, 180.1), (20.0, -180.1),
    ]
    with duckdb.connect(str(track_store)) as con:
        con.executemany(
            "INSERT INTO ais_positions VALUES (?, TIMESTAMP '2024-01-02', ?, ?, 5.0)",
            [(MMSI, lat, lon) for lat, lon in invalid],
        )
        if with_valid:
            con.execute(
                "INSERT INTO ais_positions VALUES "
                "(?, TIMESTAMP '2024-01-01', -90.0, -180.0, 5.0), "
                "(?, TIMESTAMP '2024-01-03', 90.0, 180.0, 5.0)",
                [MMSI, MMSI],
            )
    output = tools.ship_track.invoke({"mmsi": MMSI, "days": 7})
    if with_valid:
        feature = _read_feature(output)
        assert feature["properties"]["points_total"] == 2
        assert feature["geometry"]["coordinates"] == [[-180.0, -90.0], [180.0, 90.0]]
        assert "过滤空值及非法经纬度" in output
    else:
        assert "未找到" in output and "经纬度为空/非法" in output
        assert not tools.OUTPUT_DIR.exists()


def test_track_window_uses_latest_warehouse_time_and_includes_boundary(track_store):
    with duckdb.connect(str(track_store)) as con:
        con.executemany(
            "INSERT INTO ais_positions VALUES (?, ?, 10.0, ?, 5.0)",
            [
                (MMSI + 1, "2024-01-10 12:00:00", 50.0),
                (MMSI, "2024-01-09 12:00:01", 42.0),
                (MMSI, "2024-01-09 12:00:00", 41.0),
                (MMSI, "2024-01-09 11:59:59", 40.0),
                (MMSI, None, 39.0),
            ],
        )
    output = tools.ship_track.invoke({"mmsi": MMSI, "days": 1})
    feature = _read_feature(output)
    assert feature["properties"]["points_total"] == 2
    assert feature["geometry"]["coordinates"] == [[41.0, 10.0], [42.0, 10.0]]
    assert "2024-01-09 12:00:00 ~ 2024-01-09 12:00:01" in output


@pytest.mark.parametrize("days", [0, -1, -100])
def test_track_rejects_nonpositive_days_before_query(monkeypatch, days):
    def forbidden_connect():
        pytest.fail("非法 days 不应查询数据库")
    monkeypatch.setattr(tools.db, "connect", forbidden_connect)
    assert "days 必须为正整数" in tools.ship_track.invoke({"mmsi": MMSI, "days": days})


@pytest.mark.parametrize("days", [True, None, 1.5, "seven"])
def test_track_function_rejects_noninteger_days(monkeypatch, days):
    def forbidden_connect():
        pytest.fail("非法 days 不应查询数据库")
    monkeypatch.setattr(tools.db, "connect", forbidden_connect)
    assert "days 必须为正整数" in tools.ship_track.func(mmsi=MMSI, days=days)
