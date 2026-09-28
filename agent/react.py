"""ReAct Agent 主流程：想一步、做一步，直到能给出最终答案（M2）。

循环结构（langchain-core 原生 tool calling，不依赖 langchain.agents 重封装）：
    LLM 思考 -> 点名工具 -> 执行并把结果回传 -> LLM 再思考 -> ... -> 最终回答
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.messages import ToolMessage

from . import config
from .geosql import _get_llm
from .tools import ALL_TOOLS

MAX_STEPS = 8

SYSTEM_PROMPT = """你是 GeoAgent，一个空间分析智能体。你可以调用以下工具完成任务：
- geocode：地名 -> 经纬度（涉及地名时必须先调用，禁止凭印象猜坐标）
- buffer_analysis：缓冲区分析（某点周边 X 公里内的事件，输出 GeoJSON）
- ship_track：船舶航迹（MMSI -> GeoJSON 航迹线）
- query_database：通用统计/筛选查数（自然语言转 SQL）
- knowledge_search：知识库检索事件背景与相关报道（语料为英文，查询请改写为英文关键词）

工作原则：
1. 复杂问题先拆解为多步，一步一步调用工具；
2. 得到足够信息后，用中文给出条理清晰的最终回答，附上关键数字；
3. 如果工具返回了 GeoJSON 文件路径，在回答末尾列出，供地图界面渲染；
4. 不要编造工具没有返回的数据；工具失败时换思路重试或如实说明。

工具选择纪律（重要）：
- 涉及"多少起/多少艘/统计/排名/数量"的问题，必须用 query_database 或 buffer_analysis 拿精确数字，禁止只用 knowledge_search 估算；
- knowledge_search 只用于背景、原因、相关报道类问题；同一工具最多连续调用 2 次，之后必须整合信息作答或改用其他工具；
- 涉及地名坐标先 geocode，涉及"周边/附近/范围内"用 buffer_analysis。"""


@dataclass
class AgentResult:
    question: str
    answer: str = ""
    steps: list[str] = field(default_factory=list)  # 工具调用轨迹
    geojson_paths: list[str] = field(default_factory=list)
    error: str | None = None


def stream(question: str, history: list[tuple[str, str]] | None = None):
    """生成器：边执行边抛事件，供前端实时渲染工具调用过程（类 Claude Code）。

    history: [(用户问题, 助手回答), ...] 多轮记忆，注入最近 N 轮（答案截断），
             使"它/那里/再查一下"等指代可解。不传则为单轮模式。

    事件序列：
        {"type": "thinking",   "step": n}                LLM 推理中
        {"type": "tool_start", "name": ..., "args": ...} 开始调用工具
        {"type": "tool_end",   "name": ..., "output": ...} 工具返回
        {"type": "answer", "result": AgentResult}         最终回答（最后一个事件）
    """
    result = AgentResult(question=question)
    llm = _get_llm().bind_tools(ALL_TOOLS)
    tool_map = {t.name: t for t in ALL_TOOLS}

    messages = [("system", SYSTEM_PROMPT)]
    for q, a in (history or [])[-config.HISTORY_TURNS:]:
        messages.append(("human", q))
        messages.append(("ai", a[: config.HISTORY_ANSWER_CHARS]))
    messages.append(("human", question))
    for step in range(1, MAX_STEPS + 1):
        yield {"type": "thinking", "step": step}
        try:
            ai = llm.invoke(messages)
        except Exception as e:
            # LLM 网络异常（超时/限流/代理抖动）：转成友好结果而非抛堆栈
            result.error = f"LLM 请求失败：{type(e).__name__}: {e}。通常是代理延迟或限流，稍后重试即可。"
            result.answer = result.error
            yield {"type": "answer", "result": result}
            return
        messages.append(ai)

        if not ai.tool_calls:
            result.answer = ai.content
            yield {"type": "answer", "result": result}
            return

        consecutive = 0  # 连续同工具计数（防过度检索死循环）
        last_tool = None
        for call in ai.tool_calls:
            name, args = call["name"], call["args"]
            yield {"type": "tool_start", "name": name, "args": args, "step": step}
            result.steps.append(f"{name}({args})")
            try:
                output = tool_map[name].invoke(args)
            except Exception as e:
                output = f"工具执行异常：{e}"
            output = str(output)
            ev = {"type": "tool_end", "name": name, "output": output}
            if "GeoJSON 已保存：" in output:
                path = output.split("GeoJSON 已保存：")[-1].strip().splitlines()[0].strip()
                result.geojson_paths.append(path)
                ev["geojson_path"] = path  # 供前端即时上图
            yield ev
            messages.append(ToolMessage(content=output, tool_call_id=call["id"]))

            # 熔断：同一工具连调 2 次后，注入系统提示强制收敛
            consecutive = consecutive + 1 if name == last_tool else 1
            last_tool = name
            if consecutive >= 2:
                messages.append((
                    "system",
                    f"注意：你已连续多次调用 {name}。请停止重复检索，"
                    "整合已有信息直接回答；若缺少精确数字，改用 query_database "
                    "或 buffer_analysis；若信息确实不足，如实说明即可。",
                ))

    result.error = f"达到最大步数 {MAX_STEPS} 仍未收敛"
    result.answer = ai.content or result.error
    yield {"type": "answer", "result": result}


def run(question: str, verbose: bool = True, history: list[tuple[str, str]] | None = None) -> AgentResult:
    """CLI 用包装：消费 stream() 并打印过程，行为与之前一致。"""
    final: AgentResult | None = None
    for ev in stream(question, history=history):
        if not verbose:
            pass
        elif ev["type"] == "tool_start":
            print(f"[步骤 {ev['step']}] 调用 {ev['name']}({ev['args']})")
        elif ev["type"] == "tool_end":
            print(f"          -> {ev['output'][:200]}\n")
        elif ev["type"] == "answer":
            final = ev["result"]
    return final  # type: ignore[return-value]
