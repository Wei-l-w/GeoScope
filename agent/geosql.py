"""Text-to-GeoSQL 核心链路（M1）。

流程（融合 Vanna 错题本 + pandas-ai 自纠正）：
    自然语言问题
      -> schema linking（真实表结构 + 数据字典）
      -> 错题本检索相似例题（few-shot）
      -> LLM 生成 GeoSQL
      -> DuckDB 执行
      -> 报错则把错误信息回传 LLM 重写，最多重试 MAX_RETRIES 次
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import config, db, fewshot

SYSTEM_PROMPT = """你是一个空间数据分析专家，负责把用户的自然语言问题转成 DuckDB SQL（GeoSQL）。

规则：
1. 只输出一条可执行的 SELECT 语句，用 ```sql 代码块包裹，不要输出任何解释；
2. 只能使用下方给出的表和列，禁止编造表名/列名；
3. 空间过滤优先用经纬度范围（lat BETWEEN ... AND lon BETWEEN ...）；
   需要"附近/距离/缓冲区"时用公里距离公式或 spatial 函数（参考例题）；
4. 纬度合法范围 [-90, 90]，经度 [-180, 180]；
5. 结果默认加 LIMIT 1000 防止全表返回（聚合统计除外）；
6. 输出列严格限定为问题所要求的列（及其数值），不多不少：不要附加
   event_id、event_date 等未要求的列；带 ORDER BY 的 LIMIT 查询必须加
   唯一列（如主键）作为第二排序键，保证结果确定。

数据库结构：
{schema}
"""

RETRY_PROMPT = """上一次生成的 SQL 执行失败了。

失败的 SQL：
```sql
{sql}
```

DuckDB 报错：
{error}

请修正后重新输出一条完整的 SELECT 语句（仍然只用 ```sql 代码块，不要解释）。"""


@dataclass
class GeoSQLResult:
    question: str
    sql: str = ""
    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    attempts: int = 0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _get_llm():
    config.check_llm_ready()
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=config.MODEL_NAME,
        api_key=config.OPENAI_API_KEY,
        base_url=config.OPENAI_BASE_URL,
        temperature=0,
        timeout=config.LLM_TIMEOUT,        # 代理延迟高，默认超时容易误杀
        max_retries=config.LLM_RETRIES,    # 超时/限流自动重试
    )


def _extract_sql(text: str) -> str:
    m = re.search(r"```sql\s*(.*?)```", text, re.S | re.I)
    sql = (m.group(1) if m else text).strip().rstrip(";")
    if not re.match(r"(?i)^\s*select\b", sql):
        raise ValueError(f"LLM 输出不是 SELECT 语句：{sql[:120]}")
    return sql


def _build_user_prompt(question: str, spatial_ok: bool) -> str:
    examples = fewshot.retrieve(question, k=3, spatial_ok=spatial_ok)
    ex_text = "\n\n".join(f"问：{e['q']}\n```sql\n{e['sql']}\n```" for e in examples)
    return f"参考例题：\n{ex_text}\n\n用户问题：{question}"


def ask(question: str, verbose: bool = True) -> GeoSQLResult:
    """主入口：自然语言 -> GeoSQL -> 执行结果。"""
    result = GeoSQLResult(question=question)
    llm = _get_llm()

    with db.connect() as con:
        spatial_ok = db.has_spatial(con)
        schema = db.describe_schema(con)
        messages = [
            ("system", SYSTEM_PROMPT.format(schema=schema)),
            ("human", _build_user_prompt(question, spatial_ok)),
        ]

        last_error = None
        for attempt in range(1, config.MAX_RETRIES + 1):
            result.attempts = attempt
            try:
                resp = llm.invoke(messages)
            except Exception as e:
                # LLM 网络异常（代理 502/超时等）：算作一次失败尝试，继续重试
                last_error = f"LLM 请求失败：{type(e).__name__}: {e}"
                if verbose:
                    print(f"[第 {attempt} 次尝试] {last_error}\n")
                continue
            try:
                sql = _extract_sql(resp.content)
            except ValueError as e:
                last_error = str(e)
                messages += [("human", RETRY_PROMPT.format(sql=resp.content[:500], error=last_error))]
                continue
            result.sql = sql
            if verbose:
                print(f"[第 {attempt} 次尝试] SQL:\n{sql}\n")
            try:
                cur = con.execute(sql)
                result.columns = [d[0] for d in cur.description]
                result.rows = cur.fetchall()
                return result
            except Exception as e:  # 自纠正：报错回传 LLM
                last_error = str(e)
                if verbose:
                    print(f"[执行失败] {last_error}\n")
                messages += [("human", RETRY_PROMPT.format(sql=sql, error=last_error))]

        result.error = f"重试 {config.MAX_RETRIES} 次仍失败，最后的错误：{last_error}"
        return result
