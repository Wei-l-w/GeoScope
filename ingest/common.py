"""DuckDB 连接与通用入库逻辑。"""
import os
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = os.environ.get("WAREHOUSE_PATH", str(ROOT / "data" / "warehouse.duckdb"))
SCHEMA_SQL = ROOT / "db" / "schema.sql"


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(DB_PATH, read_only=read_only)


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(SCHEMA_SQL.read_text(encoding="utf-8"))


def _reader_sql(path: str, read_options: dict | None = None) -> str:
    ext = Path(path).suffix.lower()
    p = str(path).replace("'", "''").replace("\\", "/")
    if ext == ".parquet":
        return f"read_parquet('{p}')"
    if ext in (".json", ".jsonl", ".ndjson"):
        return f"read_json_auto('{p}')"
    # csv / tsv / txt；read_options 允许指定分隔符、无表头、列名等
    opts = ["sample_size=-1"]
    for k, v in (read_options or {}).items():
        if isinstance(v, bool):
            opts.append(f"{k}={'true' if v else 'false'}")
        elif isinstance(v, list):
            names = ", ".join(f"'{n}'" for n in v)
            opts.append(f"{k}=[{names}]")
        else:
            opts.append(f"{k}='{v}'")
    return f"read_csv('{p}', {', '.join(opts)})"


def _target_types(con: duckdb.DuckDBPyConnection, table: str) -> dict:
    rows = con.execute(f"PRAGMA table_info('{table}')").fetchall()
    return {r[1]: r[2] for r in rows}  # {列名: 类型}


def load_file(con: duckdb.DuckDBPyConnection, cfg: dict, path: str) -> int:
    """把一个源文件按映射配置写入目标表，返回新增行数。"""
    table = cfg["table"]
    types = _target_types(con, table)

    select_exprs = ", ".join(
        f"TRY_CAST(({expr}) AS {types[col]}) AS {col}"
        for col, expr in cfg["columns"].items()
    )

    conditions = [f"{k} IS NOT NULL" for k in cfg["key"]]
    if cfg.get("geo"):
        conditions += ["lat BETWEEN -90 AND 90", "lon BETWEEN -180 AND 180"]
    where = " AND ".join(conditions)
    key_cols = ", ".join(cfg["key"])
    col_list = ", ".join(cfg["columns"].keys())

    before = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    reader = _reader_sql(path, cfg.get("read_options"))
    con.execute(
        f"""
        INSERT INTO {table} ({col_list})
        SELECT {col_list} FROM (
            SELECT DISTINCT ON ({key_cols}) *
            FROM (SELECT {select_exprs} FROM {reader})
            WHERE {where}
        ) src
        ANTI JOIN {table} t USING ({key_cols})
        """
    )
    after = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return after - before
