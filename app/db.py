"""Streamlit 侧的数据库访问（只读）。"""
import os
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("WAREHOUSE_PATH", str(ROOT / "data" / "warehouse.duckdb"))


@st.cache_resource
def get_conn() -> duckdb.DuckDBPyConnection:
    if not Path(DB_PATH).exists():
        st.error(
            "尚未找到数据仓库文件。请先在项目根目录执行：\n\n"
            "1. `python scripts/generate_sample_data.py`（生成样例数据）\n"
            "2. `python -m ingest.load ais data/raw/ais_sample.csv` 等命令入库\n\n"
            "详见 README.md"
        )
        st.stop()
    return duckdb.connect(DB_PATH, read_only=True)


@st.cache_data(ttl=300)
def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    # 每次查询使用独立游标：多个页面/会话并发查询时共享连接不线程安全，
    # 会出现拿到别人的结果集或 None 的情况
    cur = get_conn().cursor()
    try:
        return cur.execute(sql, params).df()
    finally:
        cur.close()
