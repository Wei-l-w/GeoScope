"""样例数据生成器回归：动态 AIS 的坐标单位与静态档案的关联。

CI 与 README 的快速开始都靠这个脚本建库，而出错时的表现都是“页面照常打开、
只是没有数据”，不会报错：

- 两个生成函数若各自抽随机数，MMSI 是两个不相交的集合，入库后按 mmsi 关联
  一条都对不上，AIS 页的“船舶 / 船舶类型”筛选永远是空的；
- 动态位置若漏乘 600000，所有点会塌到 (0, 0) 附近，地图上一条船也看不见。
"""

import pytest

from scripts import generate_sample_data as sample


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(sample, "RAW", tmp_path)
    return tmp_path


def _rows(path):
    """样例文件都是 ~ 分隔、无表头，按行列拆开。"""
    return [line.split("~") for line in path.read_text(encoding="utf-8").splitlines() if line]


def _mmsi_column(path):
    return [row[0] for row in _rows(path)]


def test_static_profiles_cover_every_tracked_ship(raw):
    sample.gen_ais_static(sample.gen_ais())

    tracked = set(_mmsi_column(raw / "ais_sample.csv"))
    profiles = set(_mmsi_column(raw / "ais_static_sample.csv"))

    assert tracked, "动态 AIS 必须产出船舶"
    assert tracked == profiles, "静态档案必须与动态位置一一对应"


def test_positions_decode_to_the_documented_regions(raw):
    """第 5、6 列是 lon/lat × 600000（真实 AIS 导出格式，由 ingest/mappings 还原）。

    按映射解码后必须落在生成器用的四个海域附近：漏乘 600000 时全部塌到 0° 附近，
    这一步会失败，而不是等用户在空地图上发现。
    """
    sample.gen_ais()

    decoded = [(int(row[4]) / 600000, int(row[5]) / 600000) for row in _rows(raw / "ais_sample.csv")]
    assert decoded

    for lon, lat in decoded:
        assert any(abs(lat - region_lat) <= 5 and abs(lon - region_lon) <= 5
                   for _, region_lat, region_lon in sample.SEA_REGIONS), f"坐标偏离所有海域：{lon}, {lat}"
