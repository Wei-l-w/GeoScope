"""GeoSQL 评测器（M5）：执行准确率 = 预测 SQL 与金标 SQL 的结果集是否一致。

业界口径（Spider/BIRD）：不比 SQL 文本，比**执行结果**——同一问题可以有多种
正确写法。浮点按 0.1 容差取整后按多重集合比较，日期转字符串。

用法：
    python -m agent.eval                 # 全量 16 条（每条 1 次 LLM 调用，注意耗时）
    python -m agent.eval --limit 3       # 只跑前 3 条（冒烟）
    python -m agent.eval --tag distance  # 只跑某一类
    python -m agent.eval --out eval/report.md
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

from . import config, db, geosql

EVAL_FILE = config.ROOT / "eval" / "geosql_eval.jsonl"


def _norm_cell(v):
    if v is None:
        return "NULL"
    if isinstance(v, float):
        return f"{v:.1f}"          # 浮点 0.1 容差
    if isinstance(v, (datetime, date)):
        return str(v)[:10]
    return str(v).strip()


def _norm_rows(rows: list[tuple]) -> list[tuple]:
    return sorted(tuple(_norm_cell(c) for c in row) for row in rows)


def _load_cases(tag: str | None, limit: int | None) -> list[dict]:
    cases = [json.loads(line) for line in EVAL_FILE.read_text(encoding="utf-8").splitlines() if line.strip()]
    if tag:
        cases = [c for c in cases if tag in c.get("tags", [])]
    return cases[:limit] if limit else cases


def run_eval(cases: list[dict]) -> tuple[list[dict], dict]:
    details = []
    with db.connect() as con:
        for i, case in enumerate(cases, 1):
            t0 = time.time()
            gold_rows = _norm_rows(con.execute(case["gold_sql"]).fetchall())
            try:
                pred = geosql.ask(case["question"], verbose=False)
                pred_error = pred.error
            except Exception as e:
                # 单条用例异常（如代理长时间故障）不应中断整个评测
                pred = geosql.GeoSQLResult(question=case["question"])
                pred_error = f"评测执行异常：{type(e).__name__}: {e}"
            elapsed = time.time() - t0

            if pred_error is None:
                pred_rows = _norm_rows(pred.rows)
                match = pred_rows == gold_rows
                error = None if match else f"结果不一致：预测 {len(pred.rows)} 行 / 金标 {len(gold_rows)} 行"
            else:
                match, error = False, pred_error

            details.append({
                "id": case["id"], "tags": case.get("tags", []), "question": case["question"],
                "match": match, "attempts": pred.attempts, "elapsed_s": round(elapsed, 1),
                "pred_sql": pred.sql, "gold_sql": case["gold_sql"], "error": error,
            })
            status = "PASS" if match else "FAIL"
            print(f"[{i}/{len(cases)}] {status} {case['id']}（{pred.attempts} 次尝试，{elapsed:.0f}s）{case['question'][:30]}")

    passed = sum(1 for d in details if d["match"])
    corrected = sum(1 for d in details if d["match"] and d["attempts"] > 1)
    summary = {
        "total": len(details), "passed": passed,
        "accuracy": round(passed / len(details) * 100, 1) if details else 0.0,
        "self_corrected": corrected,
        "avg_attempts": round(sum(d["attempts"] for d in details) / len(details), 2) if details else 0,
        "avg_elapsed_s": round(sum(d["elapsed_s"] for d in details) / len(details), 1) if details else 0,
    }
    return details, summary


def write_report(details: list[dict], summary: dict, out: Path) -> None:
    lines = [
        "# GeoSQL 评测报告",
        "",
        f"- 模型：`{config.MODEL_NAME}`",
        f"- 执行准确率（execution accuracy）：**{summary['passed']}/{summary['total']} = {summary['accuracy']}%**",
        f"- 其中经自纠正后通过：{summary['self_corrected']} 条",
        f"- 平均尝试次数：{summary['avg_attempts']}；平均单条耗时：{summary['avg_elapsed_s']}s",
        "",
        "| ID | 类别 | 结果 | 尝试 | 耗时 | 问题 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for d in details:
        mark = "✅" if d["match"] else "❌"
        lines.append(f"| {d['id']} | {','.join(d['tags'])} | {mark} | {d['attempts']} | {d['elapsed_s']}s | {d['question']} |")
    lines.append("\n## 失败明细\n")
    for d in details:
        if not d["match"]:
            lines += [f"### {d['id']} {d['question']}", f"- 错误：{d['error']}",
                      f"- 预测 SQL：\n```sql\n{d['pred_sql']}\n```",
                      f"- 金标 SQL：\n```sql\n{d['gold_sql']}\n```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入 {out}")


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoSQL 执行准确率评测")
    parser.add_argument("--limit", type=int, help="只跑前 N 条")
    parser.add_argument("--tag", help="只跑某个类别（region/distance/ranking/join/...）")
    parser.add_argument("--out", type=Path, help="报告输出路径（markdown）")
    args = parser.parse_args()

    config.check_llm_ready()
    cases = _load_cases(args.tag, args.limit)
    if not cases:
        print("没有匹配的评测用例", file=sys.stderr)
        return 1
    details, summary = run_eval(cases)
    print(f"\n准确率：{summary['passed']}/{summary['total']} = {summary['accuracy']}%"
          f"（自纠正挽回 {summary['self_corrected']} 条）")
    if args.out:
        write_report(details, summary, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
