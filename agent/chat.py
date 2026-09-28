"""CLI 入口：GeoAgent 空间分析智能体。

用法：
    python -m agent.chat "曼德海峡周边150公里内有哪些高风险事件？"   # 默认 ReAct Agent 模式
    python -m agent.chat --direct "..."                              # 回退 M1 直连 GeoSQL 链
    python -m agent.chat --direct --csv out.csv "..."                # 结果导出 CSV
"""

from __future__ import annotations

import argparse
import csv
import sys


def _run_agent(question: str) -> int:
    from . import react

    try:
        result = react.run(question)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    print("=" * 60)
    print(result.answer)
    if result.geojson_paths:
        print("\nGeoJSON 输出：")
        for p in result.geojson_paths:
            print(f"  {p}")
    if result.error:
        print(f"\n[警告] {result.error}", file=sys.stderr)
        return 1
    return 0


def _run_direct(args) -> int:
    from . import geosql  # 延迟导入，--help 不需要 LLM 配置

    try:
        result = geosql.ask(args.question)
    except RuntimeError as e:  # 未配置 API Key 等环境问题的友好提示
        print(str(e), file=sys.stderr)
        return 2
    if not result.ok:
        print(f"查询失败：{result.error}", file=sys.stderr)
        return 1

    if args.sql_only:
        return 0

    print(f"共 {len(result.rows)} 行（尝试 {result.attempts} 次）：\n")
    print(" | ".join(result.columns))
    print("-" * 60)
    for row in result.rows[: args.max_rows]:
        print(" | ".join("" if v is None else str(v) for v in row))
    if len(result.rows) > args.max_rows:
        print(f"... 其余 {len(result.rows) - args.max_rows} 行省略")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(result.columns)
            writer.writerows(result.rows)
        print(f"\n已导出 {args.csv}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="GeoAgent CLI：自然语言空间分析")
    parser.add_argument("question", help="自然语言问题")
    parser.add_argument("--direct", action="store_true", help="绕过 Agent，直连 GeoSQL 链")
    parser.add_argument("--sql-only", action="store_true", help="只打印生成的 SQL（需配合 --direct）")
    parser.add_argument("--csv", metavar="PATH", help="把结果导出为 CSV（需配合 --direct）")
    parser.add_argument("--max-rows", type=int, default=20, help="终端最多打印的行数")
    args = parser.parse_args()

    if args.direct:
        return _run_direct(args)
    return _run_agent(args.question)


if __name__ == "__main__":
    sys.exit(main())
