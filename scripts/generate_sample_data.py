"""生成仿真样例数据到 data/raw/，文件格式与 ingest/mappings.py 的字段映射严格一致，
用于在无真实数据时跑通"入库 -> 可视化 -> Agent"全流程（CI 也依赖本脚本建库）。

用法: python scripts/generate_sample_data.py

产出（与 mappings 一一对应）：
- ais_sample.csv    ~ 分隔无表头 12 列，原始单位（经纬度×600000、速度/航向×10、时间戳秒）
- gdelt_sample.csv  GDELT 标准列 + EventName/country_name 增强列
- acled_sample.csv  ACLED 官方列 + 红海危机专题标注列（risk_level_v2 等）
- news_sample.jsonl 新闻抓取结果（status_code/final_url/text_preview/published_date）
"""
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(42)
random.seed(42)

END = datetime(2026, 8, 12)

SEA_REGIONS = [
    ("南海", 12.0, 113.0),
    ("波斯湾", 26.5, 52.5),
    ("黑海", 43.5, 34.0),
    ("红海", 15.0, 41.5),
]
LAND_REGIONS = [
    ("UA", "Ukraine", 48.5, 35.0),
    ("SY", "Syria", 35.0, 38.0),
    ("YE", "Yemen", 15.5, 44.5),
    ("SD", "Sudan", 15.0, 30.0),
    ("MM", "Myanmar", 21.0, 96.0),
    ("PH", "Philippines", 13.0, 122.0),
]
CHOKEPOINTS = ["Bab el-Mandeb Strait", "Suez Canal", "Strait of Hormuz"]
PORTS = ["Hodeidah", "Aden", "Jeddah", "Djibouti"]


def gen_ais():
    """~ 分隔无表头 12 列，字段与真实 AIS 导出格式一致（原始单位）。"""
    ship_types = [30, 35, 70, 80, 52]  # 渔船/军用/货船/油轮/拖轮 类型码
    rows = []
    for i in range(24):
        mmsi = 200000000 + i * 1111 + int(rng.integers(0, 999))
        _, lat0, lon0 = SEA_REGIONS[i % len(SEA_REGIONS)]
        lat, lon = lat0 + rng.uniform(-1.5, 1.5), lon0 + rng.uniform(-1.5, 1.5)
        heading = rng.uniform(0, 360)
        t = END - timedelta(days=7)
        while t <= END:
            sog = max(0.0, rng.normal(11, 4))
            heading = (heading + rng.normal(0, 12)) % 360
            dist_deg = sog * (5 / 60) / 60.0
            lat += dist_deg * np.cos(np.radians(heading))
            lon += dist_deg * np.sin(np.radians(heading))
            lat = float(np.clip(lat, lat0 - 4, lat0 + 4))
            lon = float(np.clip(lon, lon0 - 4, lon0 + 4))
            rows.append([
                mmsi, 0, "A", int(t.timestamp()),
                int(lon * 600000), int(lat * 600000),
                int((heading + rng.normal(0, 3)) % 360 * 10), int(heading), int(sog * 10),
                0, 1, int(t.timestamp()),
            ])
            t += timedelta(minutes=5)
    with open(RAW / "ais_sample.csv", "w", encoding="utf-8") as f:
        for r in rows:
            f.write("~".join(str(x) for x in r) + "\n")
    print(f"AIS: {len(rows)} 行 -> data/raw/ais_sample.csv（~ 分隔无表头）")


def gen_ais_static():
    """静态档案 ~ 分隔无表头 17 列，与 ais_static 映射一致。"""
    type_map = [(30, "渔船"), (35, "军用船"), (70, "货船"), (80, "油轮"), (52, "拖轮")]
    rows = []
    for i in range(24):
        mmsi = 200000000 + i * 1111 + int(rng.integers(0, 999))
        type_code, _ = type_map[i % len(type_map)]
        length = int(rng.integers(60, 330))
        rows.append([
            mmsi, 9000000 + i, f"CS{i:04d}", f"VESSEL-{i+1:02d}", type_code,
            length, int(length / 6), 1, "", int(rng.integers(40, 140)),
            "JEDDAH", "A", int(END.timestamp()),
            int(length * 0.3), int(length * 0.7), 5, 5,
        ])
    with open(RAW / "ais_static_sample.csv", "w", encoding="utf-8") as f:
        for r in rows:
            f.write("~".join(str(x) for x in r) + "\n")
    print(f"AIS静态: {len(rows)} 行 -> data/raw/ais_static_sample.csv")


def gen_gdelt():
    event_codes = ["010", "042", "051", "112", "130", "145", "173", "190", "193", "195"]
    actors = ["GOVERNMENT", "MILITARY", "REBELS", "CIVILIANS", "PROTESTERS",
              "UNITED STATES", "CHINA", "RUSSIA", "NATO", "UNITED NATIONS"]
    n = 6000
    regions = [LAND_REGIONS[i] for i in rng.integers(0, len(LAND_REGIONS), n)]
    dates = [END - timedelta(days=int(d)) for d in rng.integers(0, 90, n)]
    df = pd.DataFrame({
        "GLOBALEVENTID": np.arange(1_000_000, 1_000_000 + n),
        "SQLDATE": [int(d.strftime("%Y%m%d")) for d in dates],
        "Actor1Name": rng.choice(actors, n),
        "Actor2Name": rng.choice(actors, n),
        "EventCode": rng.choice(event_codes, n),
        "EventName": rng.choice(["Make public statement", "Express intent to cooperate",
                                 "Engage in negotiation", "Use conventional military force",
                                 "Fight with small arms and light weapons"], n),
        "GoldsteinScale": np.round(rng.uniform(-10, 10, n), 1),
        "AvgTone": np.round(rng.normal(-2, 3, n), 2),
        "ActionGeo_Lat": [round(r[2] + rng.normal(0, 2.5), 4) for r in regions],
        "ActionGeo_Long": [round(r[3] + rng.normal(0, 2.5), 4) for r in regions],
        "ActionGeo_CountryCode": [r[0] for r in regions],
        "ActionGeo_CountryName": [r[1] for r in regions],
        "country_name": [r[1] for r in regions],
        "NumMentions": rng.integers(1, 200, n),
        "SOURCEURL": [f"https://news.example.com/article/{i}" for i in range(n)],
    })
    df.to_csv(RAW / "gdelt_sample.csv", index=False)
    print(f"GDELT: {len(df)} 行 -> data/raw/gdelt_sample.csv")


_ACLED_NOTES = [
    "Houthi forces launched a missile attack on a merchant vessel transiting the Red Sea. "
    "The ship reported minor damage and continued its voyage toward the Suez Canal.",
    "US-led coalition conducted airstrikes on Houthi military targets in response to "
    "repeated drone attacks on commercial shipping in the Bab el-Mandeb Strait.",
    "A cargo ship was approached by small boats armed with rifles near the Yemeni coast. "
    "The vessel evaded boarding and maritime authorities were notified.",
    "Clashes erupted between government forces and rebel fighters near the port city. "
    "Artillery fire was reported throughout the night with several casualties.",
    "Protesters gathered in the capital demanding an end to the blockade. "
    "The demonstration remained peaceful and dispersed by evening.",
]


def gen_acled():
    """ACLED 官方列 + 红海危机专题标注列（与 acled 映射的 v2 字段对齐）。"""
    event_types = {
        "Battles": ["Armed clash", "Government regains territory"],
        "Explosions/Remote violence": ["Air/drone strike", "Shelling/artillery/missile attack"],
        "Protests": ["Peaceful protest", "Protest with intervention"],
        "Riots": ["Violent demonstration", "Mob violence"],
        "Violence against civilians": ["Attack", "Abduction/forced disappearance"],
    }
    types = list(event_types.keys())
    n = 2500
    rows = []
    for i in range(n):
        r = LAND_REGIONS[int(rng.integers(0, len(LAND_REGIONS)))]
        et = types[int(rng.integers(0, len(types)))]
        d = END - timedelta(days=int(rng.integers(0, 90)))
        fatal = int(max(0, rng.poisson(2) - 1)) if et != "Protests" else 0
        maritime = r[1] == "Yemen" and rng.random() < 0.5
        rows.append({
            "event_id_cnty": f"{r[0]}{10000 + i}",
            "event_date": d.strftime("%Y-%m-%d"),
            "event_type": et,
            "sub_event_type": random.choice(event_types[et]),
            "actor1": random.choice(["Military Forces", "Houthi Forces", "Protesters", "Militia"]),
            "actor2": random.choice(["Civilians", "Military Forces", "Merchant Vessel", ""]),
            "country": r[1],
            "admin1": f"{r[1]} Region-{int(rng.integers(1, 6))}",
            "location": f"Town-{int(rng.integers(1, 60))}",
            "latitude": round(r[2] + rng.normal(0, 2.0), 4),
            "longitude": round(r[3] + rng.normal(0, 2.0), 4),
            "fatalities": fatal,
            "notes": _ACLED_NOTES[i % len(_ACLED_NOTES)],
            "phase": random.choice(["precursor", "trigger_chain", "maritime_crisis"]),
            "risk_level_v2": int(rng.integers(1, 6)),
            "target_class_v2": random.choice(["vessel", "military_base", "oil_facility", "unknown"]),
            "causal_role_in_crisis": random.choice(
                ["direct_maritime_attack", "regional_escalation", "background_context"]),
            "ais_relevance_tier_v2": random.choice(
                ["tier_A_direct", "tier_A_enabling", "tier_B_signal", "tier_C_context"]),
            "actor_role": random.choice(["resistance_axis", "state_force", "coalition_response"]),
            "domain": "maritime" if maritime else random.choice(["land", "air"]),
            "is_kinetic": et != "Protests",
            "nearest_chokepoint": random.choice(CHOKEPOINTS),
            "nearest_chokepoint_km": round(float(rng.uniform(5, 300)), 1),
            "nearest_port": random.choice(PORTS),
            "nearest_port_km": round(float(rng.uniform(2, 200)), 1),
        })
    df = pd.DataFrame(rows)
    df.to_csv(RAW / "acled_sample.csv", index=False)
    print(f"ACLED: {len(df)} 行 -> data/raw/acled_sample.csv")


def gen_news(acled_ids):
    """新闻抓取结果 JSONL，与 news 映射一致（published_date 须在 2023-01~2024-06 窗口内）。"""
    bodies = [
        "Houthi forces attacked a merchant vessel in the Red Sea with anti-ship missiles, "
        "marking another escalation in the maritime crisis. The crew was reported safe, "
        "but shipping companies announced diversions around the Cape of Good Hope, "
        "adding weeks to voyage times and raising insurance premiums across the industry. "
        "Analysts warn the disruption could affect global supply chains for months. ",
        "The US-led coalition launched retaliatory strikes against Houthi radar installations "
        "and missile storage sites in Yemen. Officials described the operation as defensive, "
        "aimed at restoring freedom of navigation through the Bab el-Mandeb Strait. "
        "Regional powers called for de-escalation while shipping traffic through the "
        "strait dropped sharply, with many tankers rerouting away from the conflict zone. ",
        "A bulk carrier seized by Houthi forces remained anchored off the Yemeni coast "
        "as negotiations for the crew's release continued. The hijacking of the vessel "
        "drew international condemnation and prompted naval escorts for merchant convoys. "
        "Insurance costs for Red Sea transits surged, and major carriers suspended "
        "Suez Canal routes indefinitely, redirecting via southern Africa instead. ",
    ]
    rows = 0
    with open(RAW / "news_sample.jsonl", "w", encoding="utf-8") as f:
        for i in range(120):
            d = datetime(2023, 11, 19) + timedelta(days=int(rng.integers(0, 40)),
                                                   hours=int(rng.integers(0, 24)))
            body = bodies[i % len(bodies)] * 2  # 保证正文 >200 字符
            rec = {
                "url": f"https://media.example.com/redsea/{i}",
                "final_url": f"https://media.example.com/redsea/{i}",
                "status_code": 200,
                "title": f"Red Sea crisis update: day {i}",
                "text_preview": body,
                "published_date": d.strftime("%Y-%m-%d %H:%M:%S"),
                # 一半新闻关联到 ACLED 事件，验证 related_event_id 关联链路
                "event_id_cnty": acled_ids[i % len(acled_ids)] if i % 2 == 0 else None,
            }
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            rows += 1
    print(f"News: {rows} 行 -> data/raw/news_sample.jsonl")


if __name__ == "__main__":
    gen_ais()
    gen_ais_static()
    gen_gdelt()
    gen_acled()
    ids = [f"YE{10000 + i}" for i in range(50)]
    gen_news(ids)
    print("样例数据生成完毕。")
