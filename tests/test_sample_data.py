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


def test_speed_and_course_keep_their_tenths(raw):
    """第 7 列航向、第 9 列航速也是 ×10（mappings 里 /10.0 还原，1022/3600 为哨兵值）。

    漏乘 10 不会报错：航速全部变成 0–2.7 节，页面照常渲染，只是每条船都几乎停着。
    上下界之外还要求真的有高速样本，否则"全都恰好是 0"也能通过范围断言。
    """
    sample.gen_ais()

    rows = _rows(raw / "ais_sample.csv")
    courses = [int(row[6]) for row in rows]
    speeds = [int(row[8]) for row in rows]

    assert all(0 <= value < 3600 for value in courses), "航向应在 0–359.9 度（×10）"
    assert all(0 <= value < 1022 for value in speeds), "航速应在 0–102.1 节（×10），1022 是哨兵值"
    assert max(speeds) > 100, "样例里应有明显高于 10 节的航速，否则船在图上不动"
    assert max(courses) > 1000, "航向应铺开在整圈上，而不是挤在 0 附近"
