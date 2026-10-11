"""校验模型生成的 DuckDB 查询，并限制其数据来源、结果大小和执行时间。"""

from __future__ import annotations

import json
import math
import threading

import duckdb

from . import config, db

# 使用 DuckDB 自身解析器，避免不同 SQL 方言的解析/执行差异。
# 只开放本项目需要的计算函数；文件、网络、动态 SQL 和元数据函数均不开放。
SAFE_FUNCTIONS = frozenset("""
    + - * / // % ** ^ & | << >> ~~ !~~ ~~* !~~* ||
    abs ceil ceiling floor round trunc sqrt pow power exp ln log log10
    sin cos tan asin acos atan atan2 radians degrees pi
    count count_star sum avg min max median stddev stddev_pop stddev_samp
    variance var_pop var_samp bool_and bool_or
    coalesce ifnull nullif greatest least if
    lower upper length char_length trim ltrim rtrim substring substr
    replace concat concat_ws starts_with ends_with contains
    regexp_matches regexp_full_match regexp_replace
    date_part date_trunc date_diff datediff date_add date_sub strftime strptime
    try_strptime year month day hour minute second epoch epoch_ms
    current_date current_timestamp now today make_date make_timestamp
    to_years to_months to_days to_hours to_minutes to_seconds to_microseconds
    row_number rank dense_rank percent_rank cume_dist ntile lag lead
    first_value last_value nth_value
    st_point st_makepoint st_buffer st_dwithin st_distance st_distance_sphere
    st_distance_spheroid st_contains st_within st_intersects st_area st_length
    st_x st_y st_centroid st_astext st_asgeojson st_geomfromtext
""".split())


def _check_ast(value, tables: set[str] | None, ctes: frozenset[str] = frozenset()):
    if isinstance(value, list):
        for child in value:
            _check_ast(child, tables, ctes)
        return
    if not isinstance(value, dict):
        return

    node_type = value.get("type", "")
    if not isinstance(node_type, str):
        node_type = ""  # CONSTANT.value.type 是描述数值类型的字典。
    if node_type.endswith("_NODE") and node_type not in {"SELECT_NODE", "SET_OPERATION_NODE"}:
        raise ValueError("仅支持 SELECT 查询及非递归 CTE")
    if node_type == "TABLE_FUNCTION":
        raise ValueError("不允许表函数、文件读取或动态 SQL")
    if node_type == "BASE_TABLE":
        name = value.get("table_name", "").lower()
        schema = value.get("schema_name", "").lower()
        if value.get("catalog_name") or schema not in {"", "main"}:
            raise ValueError("只能查询当前仓库 main 中的业务表")
        if not name or any(c in name for c in "/\\.:"):
            raise ValueError("不允许文件路径作为数据表")
        if tables is not None and name not in tables and not (not schema and name in ctes):
            raise ValueError(f"不允许查询表：{name}")
    if "function_name" in value:
        name = value["function_name"].lower()
        if (name not in SAFE_FUNCTIONS or value.get("catalog")
                or value.get("schema", "").lower() not in {"", "main"}):
            raise ValueError(f"不允许调用函数：{name}")
    if value.get("class") == "PARAMETER":
        raise ValueError("模型查询不能包含未绑定参数")

    # 按声明顺序处理 CTE，避免后面的别名让前面未知的物理表绕过校验。
    local_ctes = ctes
    for entry in value.get("cte_map", {}).get("map", []):
        _check_ast(entry["value"], tables, local_ctes)
        local_ctes = local_ctes | {entry["key"].lower()}
    for key, child in value.items():
        if key != "cte_map":
            _check_ast(child, tables, local_ctes)


def validate_sql(sql: str, con=None, allowed_tables: set[str] | None = None) -> str:
    """只解析 SQL，不执行用户语句。allowed_tables=None 仅用于抽取阶段。"""
    if not sql.strip() or len(sql) > 20000:
        raise ValueError("SQL 为空或超过 20000 字符限制")
    if con is None:
        with duckdb.connect(config={"enable_external_access": False}) as parser:
            return validate_sql(sql, parser, allowed_tables)
    try:
        statements = con.extract_statements(sql)
        if len(statements) != 1 or statements[0].type != duckdb.StatementType.SELECT:
            raise ValueError("只允许单条 SELECT 查询")
        tree = json.loads(con.execute("SELECT json_serialize_sql(?)", [sql]).fetchone()[0])
    except duckdb.Error as exc:
        raise ValueError(f"SQL 解析失败：{exc}") from exc
    if tree.get("error") or len(tree.get("statements", [])) != 1:
        raise ValueError("SQL 无法解析为支持的 SELECT 查询")
    tables = None if allowed_tables is None else {name.lower() for name in allowed_tables}
    _check_ast(tree["statements"][0]["node"], tables)
    # 从已经验证的 AST 重建，正确处理末尾分号、行注释及字符串内的分号。
    return con.execute("SELECT json_deserialize_sql(?)", [json.dumps(tree)]).fetchone()[0].rstrip(";")


def execute_query(con, sql: str, *, max_rows: int | None = None,
                  timeout: float | None = None) -> tuple[list[str], list[tuple], bool]:
    """执行已限制来源的查询；截断会显式返回，超时中断后连接仍可使用。"""
    max_rows = config.MAX_QUERY_ROWS if max_rows is None else max_rows
    timeout = config.QUERY_TIMEOUT if timeout is None else timeout
    if not isinstance(max_rows, int) or max_rows < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("查询行数上限和超时必须大于零")
    validated_query = validate_sql(sql, con, set(db.TABLE_COMMENTS))
    # spatial 如需使用，应由调用方提前加载；生成的 SQL 不能触发外部访问。
    con.execute("SET enable_external_access = false")
    con.execute("SET autoinstall_known_extensions = false")
    con.execute("SET autoload_known_extensions = false")
    query = f"SELECT * FROM (\n{validated_query}\n) AS _geoagent_result LIMIT {max_rows + 1}"
    finished = threading.Event()
    expired = threading.Event()

    def interrupt_on_timeout():
        if not finished.wait(timeout):
            expired.set()
            # 重复中断覆盖首次 interrupt 刚好发生在 execute 开始前的竞态。
            while not finished.is_set():
                con.interrupt()
                finished.wait(0.01)

    watchdog = threading.Thread(target=interrupt_on_timeout, daemon=True)
    watchdog.start()
    try:
        cur = con.execute(query)
        columns = [column[0] for column in cur.description]
        rows = cur.fetchmany(max_rows + 1)
    except duckdb.Error as exc:
        if expired.is_set():
            raise TimeoutError(f"查询超过 {timeout:g} 秒，已中断") from exc
        raise
    finally:
        finished.set()
        watchdog.join()
    if expired.is_set():
        raise TimeoutError(f"查询超过 {timeout:g} 秒，已中断")
    return columns, rows[:max_rows], len(rows) > max_rows
