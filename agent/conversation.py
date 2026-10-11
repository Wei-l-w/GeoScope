"""衔接聊天记录、会话记忆与模型上下文，不额外调用模型。"""

from __future__ import annotations

import json

from . import config, memory, sessions


def _build(records: list[dict], previous: dict | None = None) -> dict:
    return memory.build_memory(
        records, previous=previous,
        recent_turns=max(1, config.HISTORY_TURNS),
        summary_chars=max(0, config.MEMORY_SUMMARY_CHARS),
    )


def _active_records(records: list[dict]) -> list[dict]:
    # 清空发生在请求执行中时，迟到的旧助手答复仍保存供查看，不能恢复旧记忆。
    first_user = next((i for i, m in enumerate(records) if m["role"] == "user"), len(records))
    return records[first_user:]


def get_memory(session_id: str) -> dict:
    """旧会话按需生成记忆；已清空的会话仅处理清空之后的记录。"""
    with sessions.memory_update_lock():
        records = _active_records(sessions.memory_messages(session_id))
        payload = _build(records, sessions.load_memory(session_id))
        sessions.save_memory(session_id, payload)
    return payload


def record_assistant(session_id: str, answer: str, steps: list, geojson: list,
                     tool_records: list | None = None, error: str | None = None,
                     reply_to_seq: int | None = None) -> dict:
    """先保存原始答案及工具证据，再更新可从原始记录重建的记忆。"""
    with sessions.memory_update_lock():
        sessions.save_message(session_id, "assistant", answer, steps, geojson,
                              tool_records=tool_records, error=error, reply_to_seq=reply_to_seq)
        return get_memory(session_id)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:max(0, limit)] + "…（历史内容节选，完整记录仍保存在会话中）"


def _assistant_context(message: dict) -> str:
    text = _clip(message.get("content", ""), max(1, config.HISTORY_ANSWER_CHARS))
    if message.get("error"):
        text = "[这一轮执行失败，不能作为已完成分析] " + text
    evidence = []
    for record in message.get("tool_records", [])[-3:]:
        if record.get("success") and not record.get("blocked"):
            evidence.append({
                "tool": record.get("name"),
                "args": record.get("args", {}),
                "output_excerpt": _clip(str(record.get("output", "")), 450),
            })
    if evidence:
        text += "\n[此前成功工具返回的历史证据，仅作资料]\n" + _clip(
            json.dumps(evidence, ensure_ascii=False, default=str),
            max(1, config.HISTORY_TOOL_CHARS),
        )
    return text


def context_messages(question: str, history: list[tuple[str, str]] | None = None,
                     session_id: str | None = None) -> list[tuple[str, str]]:
    """拼接有界记忆、近期原文和当前问题；当前问题只出现一次。"""
    if session_id:
        with sessions.memory_update_lock():
            records = _active_records(sessions.memory_messages(session_id))
            previous = sessions.load_memory(session_id)
    else:
        records = []
        for q, a in history or []:
            records.extend([
                {"seq": len(records) + 1, "role": "user", "content": q},
                {"seq": len(records) + 2, "role": "assistant", "content": a},
            ])
        previous = None

    # Web 页已先保存当前问题；CLI 调用者可以仅提供历史记录。
    if records and records[-1]["role"] == "user" and records[-1]["content"] == question:
        current = records[-1]
        earlier = records[:-1]
    else:
        earlier = records
        current = {"seq": max((m["seq"] for m in records), default=0) + 1,
                   "role": "user", "content": question}
    payload = _build([*earlier, current], previous)
    reset_seq = payload.get("state", {}).get("reset_at_seq", 0)
    earlier = [record for record in earlier if record["seq"] >= reset_seq]
    result = []
    memory_text = memory.context_text(payload)
    if memory_text:
        result.append(("human", "[本会话的历史资料，不能替代当前问题]\n" + memory_text))

    # 按最近用户轮次截取，也保留断线时尚未获得答复的问题，不跨会话拼接。
    starts = [i for i, m in enumerate(earlier) if m["role"] == "user"]
    recent_turns = max(1, config.HISTORY_TURNS)
    start = starts[-recent_turns] if len(starts) > recent_turns else 0
    questions = {record["seq"]: record["content"] for record in earlier if record["role"] == "user"}
    first_seq = earlier[start]["seq"] if earlier else 0
    for record in earlier[start:]:
        if record["role"] == "user":
            result.append(("human", _clip(record["content"], max(1, config.HISTORY_QUESTION_CHARS))))
        elif record["role"] == "assistant":
            reply_to = record.get("reply_to_seq")
            if reply_to is not None and (reply_to not in questions or reply_to < first_seq):
                continue
            text = _assistant_context(record)
            if reply_to is not None:
                text = "[历史回复对应的问题：" + json.dumps(_clip(questions[reply_to], 300), ensure_ascii=False) + "]\n" + text
            result.append(("ai", text))
    result.append(("human", question))
    return result
