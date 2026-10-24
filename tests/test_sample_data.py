"""样例数据生成器回归：动态 AIS 与静态档案必须能按 MMSI 关联。

CI 与 README 的快速开始都靠这个脚本建库。两个生成函数若各自抽随机数，
得到的 MMSI 是两个不相交的集合，入库后 CREATE/LATERAL JOIN 一条都对不上：
七个页面照常打开、不会报错，但 AIS 页的“船舶 / 船舶类型”筛选永远是空的。
"""

import pytest

from scripts import generate_sample_data as sample


@pytest.fixture
def raw(tmp_path, monkeypatch):
    monkeypatch.setattr(sample, "RAW", tmp_path)
    return tmp_path


def _mmsi_column(path):
    return [line.split("~")[0] for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_static_profiles_cover_every_tracked_ship(raw):
    sample.gen_ais_static(sample.gen_ais())

    tracked = set(_mmsi_column(raw / "ais_sample.csv"))
    profiles = set(_mmsi_column(raw / "ais_static_sample.csv"))

    assert tracked, "动态 AIS 必须产出船舶"
    assert tracked == profiles, "静态档案必须与动态位置一一对应"
