"""查询保护的行为回归：只用内存 DuckDB 和模型替身。"""

from types import SimpleNamespace

import duckdb
import pytest

from agent import db, fewshot, geosql, sql_guard


@pytest.fixture
def warehouse():
    with duckdb.connect() as con:
        con.execute("CREATE TABLE ais_positions AS SELECT i AS n FROM range(1000) t(i)")
        yield con


@pytest.mark.parametrize("sql", [
    "SELECT 1; SELECT 2",
    "SELECT 1; DROP TABLE ais_positions",
    "COPY (SELECT 1) TO 'out.csv'",
    "PRAGMA version", "INSTALL spatial", "SET enable_external_access=true",
    "DELETE FROM ais_positions RETURNING *",
    "SELECT * FROM read_csv_auto('private.csv')",
    "SELECT * FROM read_parquet('https://example.com/data.parquet')",
    "SELECT * FROM query('SELECT 1')",
    "SELECT * FROM 'private.csv'",
    "SELECT * FROM information_schema.tables",
    "SELECT * FROM other.main.ais_positions",
    "SELECT * FROM secret_table",
    "SELECT getenv('SECRET')", "SELECT nextval('s')",
    "SELECT * FROM (SELECT * FROM read_blob('private.txt')) t",
    "SELECT (SELECT COUNT(*) FROM secret_table)",
    "WITH x AS (SELECT * FROM secret_table), secret_table AS (SELECT 1) SELECT * FROM x",
    "WITH RECURSIVE x AS (SELECT 1 n UNION ALL SELECT n+1 FROM x) SELECT * FROM x",
    "SELECT ?", "", "SELECT (",
])
def test_reject_unsafe_queries(sql):
    # 只解析而不执行，测试字符串里的路径/URL 从不被访问。
    with pytest.raises(ValueError):
        sql_guard.validate_sql(sql, allowed_tables=set(db.TABLE_COMMENTS))


@pytest.mark.parametrize("example", fewshot.EXAMPLES, ids=lambda item: item["q"][:20])
def test_existing_spatial_examples_remain_valid(example):
    assert sql_guard.validate_sql(example["sql"], allowed_tables=set(db.TABLE_COMMENTS))


def test_cte_join_and_semicolon_in_string(warehouse):
    columns, rows, truncated = sql_guard.execute_query(warehouse, """
        WITH a AS (SELECT n FROM ais_positions WHERE n < 3),
             b AS (SELECT n FROM a)
        SELECT a.n, 'x;y' AS marker FROM a JOIN b USING (n) ORDER BY a.n;
        -- 最后一条注释不会让包裹后的语句失效
    """)
    assert columns == ["n", "marker"]
    assert rows == [(0, "x;y"), (1, "x;y"), (2, "x;y")]
    assert not truncated


def test_rows_are_capped_and_truncation_is_explicit(warehouse):
    _, rows, truncated = sql_guard.execute_query(
        warehouse, "SELECT n FROM ais_positions ORDER BY n", max_rows=5)
    assert rows == [(n,) for n in range(5)]
    assert truncated
    _, rows, truncated = sql_guard.execute_query(
        warehouse, "SELECT n FROM ais_positions ORDER BY n LIMIT 5", max_rows=5)
    assert len(rows) == 5 and not truncated
    # 只限制结果行数，聚合仍必须读取完整数据并给出正确总数。
    assert sql_guard.execute_query(warehouse, "SELECT COUNT(*) FROM ais_positions", max_rows=5)[1] == [(1000,)]


def test_timeout_interrupts_real_query_and_connection_recovers(warehouse):
    with pytest.raises(TimeoutError, match="已中断"):
        sql_guard.execute_query(warehouse, """
            SELECT SUM(a.n * b.n + c.n)
            FROM ais_positions a CROSS JOIN ais_positions b CROSS JOIN ais_positions c
        """, timeout=0.03)
    assert sql_guard.execute_query(warehouse, "SELECT 42")[1] == [(42,)]


def test_external_access_is_disabled(warehouse):
    sql_guard.execute_query(warehouse, "SELECT 1")
    assert warehouse.execute("SELECT current_setting('enable_external_access')").fetchone() == (False,)


def test_ask_retries_invalid_sql_then_returns_capped_result(monkeypatch):
    con = duckdb.connect()
    con.execute("CREATE TABLE ais_positions AS SELECT i AS n FROM range(6) t(i)")
    replies = iter(["SELECT 1; SELECT 2", "SELECT n FROM ais_positions ORDER BY n"])
    prompts = []

    def invoke(messages):
        prompts.append(list(messages))
        return SimpleNamespace(content=next(replies))

    monkeypatch.setattr(geosql, "_get_llm", lambda: SimpleNamespace(invoke=invoke))
    monkeypatch.setattr(db, "connect", lambda: con)
    monkeypatch.setattr(db, "has_spatial", lambda _: False)
    monkeypatch.setattr(geosql.config, "MAX_QUERY_ROWS", 3)
    result = geosql.ask("列出位置", verbose=False)
    assert result.ok and result.attempts == 2
    assert result.rows == [(0,), (1,), (2,)] and result.truncated
    assert "只允许单条" in prompts[1][-1][1]


def test_tool_discloses_truncated_results(monkeypatch):
    from agent.tools import query_database

    monkeypatch.setattr(geosql, "ask", lambda *args, **kwargs: geosql.GeoSQLResult(
        question="测试", columns=["n"], rows=[(1,)], truncated=True))
    assert "不是全部记录" in query_database.invoke({"question": "列出全部"})
