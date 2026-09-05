"""生成仿真样例数据到 data/raw/，列名与各数据源官方格式一致，
用于在真实数据到位前跑通"入库 -> 可视化"全流程。

用法: python scripts/generate_sample_data.py
"""
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

# 热点海域 (名称, 纬度, 经度)
SEA_REGIONS = [
    ("南海", 12.0, 113.0),
    ("波斯湾", 26.5, 52.5),
    ("黑海", 43.5, 34.0),
    ("红海", 15.0, 41.5),
]
# 热点陆地区域 (国家代码, 国家名, 纬度, 经度)
LAND_REGIONS = [
    ("UA", "Ukraine", 48.5, 35.0),
    ("SY", "Syria", 35.0, 38.0),
    ("YE", "Yemen", 15.5, 44.5),
    ("SD", "Sudan", 15.0, 30.0),
    ("MM", "Myanmar", 21.0, 96.0),
    ("PH", "Philippines", 13.0, 122.0),
]


def gen_ais():
    ship_types = ["Cargo", "Tanker", "Fishing", "Passenger", "Military"]
    rows = []
    for i in range(24):
        mmsi = 200000000 + i * 1111 + int(rng.integers(0, 999))
        name = f"VESSEL-{i+1:02d}"
        stype = ship_types[i % len(ship_types)]
        _, lat0, lon0 = SEA_REGIONS[i % len(SEA_REGIONS)]
        lat, lon = lat0 + rng.uniform(-1.5, 1.5), lon0 + rng.uniform(-1.5, 1.5)
        heading = rng.uniform(0, 360)
        t = END - timedelta(days=7)
        while t <= END:
            sog = max(0.0, rng.normal(11, 4))
            heading = (heading + rng.normal(0, 12)) % 360
            # 5 分钟位移（近似度数换算）
            dist_deg = sog * (5 / 60) / 60.0
            lat += dist_deg * np.cos(np.radians(heading))
            lon += dist_deg * np.sin(np.radians(heading))
            lat = float(np.clip(lat, lat0 - 4, lat0 + 4))
            lon = float(np.clip(lon, lon0 - 4, lon0 + 4))
            rows.append({
                "MMSI": mmsi,
                "BaseDateTime": t.strftime("%Y-%m-%dT%H:%M:%S"),
                "LAT": round(lat, 5),
                "LON": round(lon, 5),
                "SOG": round(sog, 1),
                "COG": round(heading + rng.normal(0, 3), 1) % 360,
                "Heading": round(heading, 1),
                "VesselName": name,
                "VesselType": stype,
            })
            t += timedelta(minutes=5)
    df = pd.DataFrame(rows)
    df.to_csv(RAW / "ais_sample.csv", index=False)
    print(f"AIS: {len(df)} 行 -> data/raw/ais_sample.csv")


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
        "GoldsteinScale": np.round(rng.uniform(-10, 10, n), 1),
        "AvgTone": np.round(rng.normal(-2, 3, n), 2),
        "ActionGeo_Lat": [round(r[2] + rng.normal(0, 2.5), 4) for r in regions],
        "ActionGeo_Long": [round(r[3] + rng.normal(0, 2.5), 4) for r in regions],
        "ActionGeo_CountryCode": [r[0] for r in regions],
        "NumMentions": rng.integers(1, 200, n),
        "SOURCEURL": [f"https://news.example.com/article/{i}" for i in range(n)],
    })
    df.to_csv(RAW / "gdelt_sample.csv", index=False)
    print(f"GDELT: {len(df)} 行 -> data/raw/gdelt_sample.csv")


def gen_acled():
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
        rows.append({
            "event_id_cnty": f"{r[0]}{10000 + i}",
            "event_date": d.strftime("%Y-%m-%d"),
            "event_type": et,
            "sub_event_type": random.choice(event_types[et]),
            "actor1": random.choice(["Military Forces", "Rebel Group", "Protesters", "Militia"]),
            "actor2": random.choice(["Civilians", "Military Forces", "Rebel Group", ""]),
            "country": r[1],
            "admin1": f"{r[1]} Region-{int(rng.integers(1, 6))}",
            "location": f"Town-{int(rng.integers(1, 60))}",
            "latitude": round(r[2] + rng.normal(0, 2.0), 4),
            "longitude": round(r[3] + rng.normal(0, 2.0), 4),
            "fatalities": fatal,
            "notes": f"Sample event near {r[1]}.",
        })
    df = pd.DataFrame(rows)
    df.to_csv(RAW / "acled_sample.csv", index=False)
    print(f"ACLED: {len(df)} 行 -> data/raw/acled_sample.csv")


def gen_news():
    topics = [
        ("南海局势", "南海 航行自由 军舰 对峙 渔船 岛礁"),
        ("红海航运", "红海 商船 袭击 航线 绕行 保险"),
        ("乌克兰冲突", "乌克兰 无人机 前线 停火 谈判 援助"),
        ("中东局势", "叙利亚 也门 空袭 武装 平民 人道主义"),
        ("能源运输", "油轮 波斯湾 原油 出口 制裁 港口"),
        ("缅甸局势", "缅甸 边境 冲突 难民 停火 谈判"),
    ]
    sources = ["新华社", "路透社", "美联社", "半岛电视台", "BBC", "CNN"]
    rows = []
    for i in range(600):
        topic, words = topics[int(rng.integers(0, len(topics)))]
        kw = words.split()
        random.shuffle(kw)
        d = END - timedelta(days=int(rng.integers(0, 90)), hours=int(rng.integers(0, 24)))
        title = f"{topic}最新进展：{kw[0]}相关动态引关注"
        body = (f"据报道，近期{topic}持续发展。有关{('、'.join(kw[:4]))}等方面的消息显示，"
                f"局势仍在变化之中。分析人士指出，{kw[4 % len(kw)]}问题值得持续关注。"
                f"多方呼吁通过对话解决分歧。")
        rows.append({
            "id": f"news-{i:05d}",
            "published_at": d.strftime("%Y-%m-%d %H:%M:%S"),
            "source": random.choice(sources),
            "title": title,
            "body": body,
            "url": f"https://media.example.com/{i}",
            "lang": "zh",
        })
    df = pd.DataFrame(rows)
    df.to_csv(RAW / "news_sample.csv", index=False)
    print(f"News: {len(df)} 行 -> data/raw/news_sample.csv")


if __name__ == "__main__":
    gen_ais()
    gen_gdelt()
    gen_acled()
    gen_news()
    print("样例数据生成完毕。")
