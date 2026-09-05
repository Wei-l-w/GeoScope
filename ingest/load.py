"""通用入库命令行工具。

用法（在项目根目录执行）：
    python -m ingest.load ais   data/raw/ais_sample.csv
    python -m ingest.load gdelt data/raw/gdelt_*.csv
    python -m ingest.load acled data/raw/acled_sample.csv
    python -m ingest.load news  data/raw/news_sample.csv

支持 CSV / Parquet / JSON，支持通配符批量导入，重复导入自动去重。
"""
import argparse
import glob
import sys

from ingest.common import connect, ensure_schema, load_file
from ingest.mappings import MAPPINGS


def main() -> int:
    parser = argparse.ArgumentParser(description="数据入库工具")
    parser.add_argument("source", choices=sorted(MAPPINGS.keys()), help="数据源类型")
    parser.add_argument("paths", nargs="+", help="文件路径（支持通配符）")
    args = parser.parse_args()

    # 含通配符的路径直接交给 DuckDB 批量读取（一次去重插入，比逐文件快得多）
    files = []
    for p in args.paths:
        if "*" in p or "?" in p:
            if not glob.glob(p):
                print(f"[警告] 未找到文件: {p}")
                continue
            files.append(p)
        elif glob.glob(p):
            files.append(p)
        else:
            print(f"[警告] 未找到文件: {p}")
    if not files:
        print("[错误] 没有可导入的文件")
        return 1

    cfg = MAPPINGS[args.source]
    con = connect()
    ensure_schema(con)
    total = 0
    for f in files:
        try:
            n = load_file(con, cfg, f)
        except Exception as e:
            print(f"[失败] {f}: {e}")
            print("提示: 若列名不匹配，请修改 ingest/mappings.py 中的字段映射")
            return 1
        total += n
        print(f"[完成] {f}: 新增 {n} 行")
    count = con.execute(f"SELECT COUNT(*) FROM {cfg['table']}").fetchone()[0]
    print(f"共新增 {total} 行，表 {cfg['table']} 当前总量 {count} 行")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
