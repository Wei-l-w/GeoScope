"""地理编码回归：项目高频地名以内置地名库为准，只有库外的地名才查 Nominatim。

验收时发现的真实故障：`geocode("曼德海峡")` 打给公共 Nominatim，返回的前三个候选
全是闽侯县、福州和法国诺曼底的无关地点（福建的“海峡传媒港”等），而工具照单全收，
还把“取第一个最准”写在最前面。会话记忆又只取输出里第一个 lat/lon，于是侧栏“本会话
记忆”里曼德海峡的坐标变成了 26.14, 119.13（福州）——此后任何工具都无法再用 12.58
覆盖它，因为已记录的坐标来源是 tool:geocode。

内置地名库本来就是为这批地名准备的，只是过去仅当作断网兜底。让它优先命中的好处是
结果确定、可离线复现；库外地名（如某个港口小镇）仍走在线服务。
"""

import pytest

from agent import tools


class _Response:
    def __init__(self, hits):
        self._hits = hits

    def raise_for_status(self):
        return None

    def json(self):
        return self._hits


def _fake_nominatim(monkeypatch, hits=None, error=None):
    """替换在线请求，并记录是否真的被调用过（库内地名不应联网）。"""
    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params)
        if error:
            raise error
        return _Response(hits or [])

    monkeypatch.setattr(tools.requests, "get", fake_get)
    return calls


def test_curated_chokepoint_wins_over_unrelated_online_candidates(monkeypatch):
    """库内地名必须给出人工维护的坐标，且完全不联网。

    在线服务对中文地名的前几条命中可能是同名或近名的无关地点；验收时第一个候选
    就是福州的“海峡传媒港”，坐标偏了两千多公里。
    """
    calls = _fake_nominatim(monkeypatch, hits=[
        {"display_name": "海峡传媒港, 甘蔗街道, 闽侯县, 福州市, 福建省, 中国",
         "lat": "26.1433576", "lon": "119.1354631"},
        {"display_name": "Manoir de Bévilliers, Normandie, France",
         "lat": "49.5147035", "lon": "0.2178991"},
    ])

    result = tools.geocode.invoke({"place": "曼德海峡"})

    assert calls == [], "库内地名不应联网，否则同一问题每天答案都可能不同"
    assert "lat=12.58, lon=43.33" in result
    assert "26.14" not in result and "119.13" not in result


def test_english_name_of_a_curated_place_maps_to_the_same_coordinates(monkeypatch):
    """中英文写法要落到同一坐标；验收时模型正是先问中文、再问英文。"""
    _fake_nominatim(monkeypatch, hits=[])

    zh = tools.geocode.invoke({"place": "曼德海峡"})
    en = tools.geocode.invoke({"place": "Bab el-Mandeb Strait"})

    assert "lat=12.58, lon=43.33" in zh
    assert "lat=12.58, lon=43.33" in en


def test_place_outside_the_gazetteer_still_uses_online_candidates(monkeypatch):
    """库外地名不能被吞掉：仍要联网并原样给出候选。"""
    calls = _fake_nominatim(monkeypatch, hits=[
        {"display_name": "Port of Djibouti, Djibouti", "lat": "11.6", "lon": "43.15"},
    ])

    result = tools.geocode.invoke({"place": "多哈港"})

    assert calls and calls[0]["q"] == "多哈港"
    assert "Port of Djibouti" in result
    assert "lat=11.6, lon=43.15" in result


def test_online_failure_outside_the_gazetteer_reports_an_actionable_error(monkeypatch):
    _fake_nominatim(monkeypatch, error=TimeoutError("timed out"))

    result = tools.geocode.invoke({"place": "多哈港"})

    assert "地理编码服务不可用" in result
    assert "query_database" in result


def test_empty_online_result_outside_the_gazetteer_suggests_another_name(monkeypatch):
    _fake_nominatim(monkeypatch, hits=[])

    result = tools.geocode.invoke({"place": "多哈港"})

    assert "未找到地名" in result


@pytest.mark.parametrize("place", ["峡", "海", "湾"])
def test_single_character_does_not_hit_a_curated_name(place):
    """`p in name` 是双向包含匹配：一个汉字不应被当成“曼德海峡”的简称。"""
    assert tools._gazetteer_lookup(place) is None
