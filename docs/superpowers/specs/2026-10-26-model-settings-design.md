# 模型手动配置（Base URL / API Key / 模型名）

日期：2026-10-26
状态：已确认，待实现

## 1. 背景

现在模型参数只能改项目根的 `.env`（`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `MODEL_NAME`），
改完要重启应用。用户希望在界面里直接填写并切换模型。

## 2. 目标

- 在应用内填写 Base URL、API Key、模型名，保存后立刻生效（下一轮分析使用新配置）。
- 保存时用新配置发一次最小真实请求，成功才落盘；失败显示具体错误，且**不覆盖**原有可用配置。
- 提供"恢复默认"：删除本地配置，回到 `.env` / 环境变量。
- 存储只在本机，不进入 git。

## 3. 非目标

- 不做多套配置的命名保存与快速切换（YAGNI；以后要再加）。
- 不改看板页：六个看板页不调用模型，模型配置只影响工作台与 CLI。
- 不做密钥加密存储。本地明文文件与 `.env` 是同等级别，加密需要一个用户口令，超出本次范围。

## 4. 设计

### 4.1 分层

```
agent/config.py          环境变量 / .env  →  默认值层（不变）
agent/model_config.py    本地 JSON 文件    →  覆盖层（新增）
```

`model_config.current()` 返回合并结果：

```python
@dataclass(frozen=True)
class ModelSettings:
    base_url: str   # 可为空，空 = 使用官方接口
    api_key: str
    model: str
    source: str     # "file" | "env"
```

合并规则：本地文件的 `api_key` 与 `model` 都非空时才生效，否则整体回落到 `.env`。
`base_url` 允许为空（官方接口的情形）。

`config.check_llm_ready()` 改为读取合并结果；为避免 `config → model_config → config`
的循环导入，在函数体内延迟导入 `model_config`。

**一轮之内配置不变**：`model_config.frozen()` 用 `ContextVar` 冻结这一轮的 `ModelSettings`
与密钥快照，产出 `(settings, secrets)`，退出时 `reset`。`active()` 返回"本轮冻结的配置，
没有冻结时读最新配置"。`react.stream`、`app.workspace.run_analysis`、`agent.chat` 的两个入口
各冻结一次；嵌套的 `geosql.ask`（`query_database` 工具）复用外层那一份，不会在同一轮里
换成另一个标签页刚保存的模型。并发请求在不同执行上下文里，互不可见。

`react.stream` 另有一层：`ContextVar` 按**执行上下文**隔离，不按生成器隔离。若把
`with frozen()` 直接写在生成器体里，`yield` 出去时调用方仍停在冻结态（另一轮读不到新配置），
而 `close()` 的 `token.reset` 还可能发生在另一个上下文里（`ValueError: was created in a
different Context`）。所以公共 `stream()` 只做驱动：每次 `next` 与最终的 `close` 都在
`copy_context()` 出来的那份上下文里跑，事件 `yield` 回调用方自己的上下文。生成器因此
可以在任意位置暂停、被持有、跨上下文关闭，都不会污染消费者，也不会留下过期状态。

### 4.2 存储

- 路径：`data/model_settings.json`。`.gitignore` 只按子路径排除了部分 `data/` 内容，
  因此需要精确新增 `data/model_settings.json` 与其 `.tmp` 两条。
- 内容：`{"base_url": "...", "api_key": "...", "model": "..."}`。
- 写入：先写 `model_settings.json.tmp` 再 `os.replace()` 原子替换，避免写一半断电留下损坏文件；
  POSIX 上额外 `chmod 0600`。
- 读取：文件缺失、非 UTF-8、JSON 损坏、字段类型不对、超过体积上限（8 KB）、
  超长整数或极深嵌套导致的 `ValueError` / `RecursionError` → 一律当作"没有本地配置"，
  不报错、不中断页面。
  类型不对指任何字段：`base_url` 写坏了（含显式 `null`）也整份作废，不能洗成空串后改用官方接口。
  只有"键不存在"才视为官方接口（旧版本或手写文件）。
- 写入与删除共用一把进程内锁：两个线程并行写会互相截断同一个 `.tmp`；
  删除与替换交错则可能"删掉之后又被写回来"。

### 4.3 校验

保存前：

1. `api_key`、`model` 非空；`base_url` 可空，非空时必须是 `http://` 或 `https://` 且带主机名。
2. 每个字段长度上限 500 字符（防止误粘贴整段内容）。
3. 真实连通测试：用 `langchain_openai.ChatOpenAI`（与生产同一个客户端类）发一条短提示，
   `timeout=20`、`max_retries=0`。成功返回 `(True, "连接正常")`，失败返回
   `(False, "异常类型: 摘要")`。
4. 错误摘要必须把 API Key 原文替换成 `***` 再展示——代理报错有时会回显请求头。
   同一处理也覆盖生产调用路径（`agent/react.py`、`agent/geosql.py`、`app/workspace.py`、
   `agent/chat.py`、`agent/eval.py`）：那些报错会显示在对话里、打到终端、写进报告与会话库，
   同样不该带着密钥落盘。工具输出（包括工具自己捕获异常后返回的"查询失败：…"）
   在展示、入库、喂回模型之前统一过同一个脱敏点。

任何一步失败都不写文件。

**Base URL 留空的实际含义**：必须显式解析成 `https://api.openai.com/v1` 再交给客户端。
客户端在 `base_url=None` 时会回读 `OPENAI_BASE_URL` / `OPENAI_API_BASE` 环境变量，
而本项目 `.env` 里正好写着代理地址——"留空使用官方接口"会变成"把新 Key 发到旧代理"。

### 4.4 界面

位置：工作台侧栏底部，`st.popover` 触发器显示当前模型名与来源：

- `模型 · gpt-6-luna（本地配置）`
- `模型 · deepseek-chat（.env）`

弹窗内容（`st.form`）：

| 控件 | 行为 |
| --- | --- |
| Base URL（文本） | 占位符"留空使用官方接口"；预填当前值 |
| API Key（密码） | 预填当前值；不回显明文 |
| 模型名（文本） | 预填当前值 |
| 保存并测试（提交按钮） | 校验 → 试连 → 成功落盘并 `st.rerun()`；失败 `st.error` 且不落盘 |
| 恢复默认（普通按钮） | 删除本地文件（回调触发重跑）；没有本地配置时置灰；删不掉时提示而不是静默 |

分析进行中（`busy`）整个触发器置灰，与其他侧栏控件一致。实测 `st.popover(disabled=True)`
只禁用触发按钮，已展开的菜单体在前端仍会保留，所以里面的"保存并测试""恢复默认"各自也要
按 `busy` 置灰。

### 4.5 与 CLI 的关系

`agent.chat` 与 `agent.eval` 走同一个 `_get_llm()`，因此界面里保存的配置对它们同样生效。
这是想要的：用户不必在两个地方各配一份。

评测报告里的模型名在**开跑时**记下（写进 `summary["model"]`），不在写报告时现读：
一次评测可能跑很久，中途改配置会让报告张冠李戴。

## 5. 测试

`tests/test_model_settings.py`（全部离线，不访问网络）：

- 读写往返；`save` 后无残留 `.tmp` 文件。
- 文件损坏 / 字段缺失 / 非对象 / 非 UTF-8 / 任一字段类型不对 → `load()` 返回 `None`，`current()` 回落 `.env`。
- 合并优先级：有文件时用文件；无文件时用环境变量；缺 `base_url` 键的文件仍按"官方接口"生效。
- 病态文件：显式 `null`、超长整数（5000 位）、极深嵌套（`RecursionError`）、超过体积上限的
  文件——各自回落 `.env`，不抛异常。
- 校验：空 key、空模型名、`ftp://`、超长字段（含 Base URL 本身超长）各自被拒。
- `test_connection`：用桩替换 `ChatOpenAI`，覆盖成功与抛异常两条路径；断言异常信息里的 Key 被替换成 `***`。
- 真实请求地址：用 `httpx.MockTransport` 跑真实客户端（不联网），断言"留空"实际打到
  `https://api.openai.com/v1/chat/completions`，不会被环境里的 `OPENAI_BASE_URL` / `OPENAI_API_BASE` 劫持；
  填了中转地址则打到该地址；生产客户端 `_get_llm` 走同一条解析。
- `redact()`：不带 secret 参数时，本地配置与 `.env` 两层的 Key 都被替换；
  一份快照里短 Key 是长 Key 的前缀时，先换长的，不留半截尾巴。
- 工具输出统一脱敏：工具**抛异常**与工具**自己捕获后返回"查询失败：…"**两条路径都要过；
  断言事件里的 `output`、`tool_records`、下一轮喂给模型的 `ToolMessage` 三处都不含密钥，
  `artifact_error` 也要覆盖。每条断言都已用"删掉对应代码"的反向验证确认会失败。
- 触发器文案：`trigger_label()` 直接单测，AppTest 只负责确认它渲染到了侧栏上。
- AppTest：打开工作台，弹窗三个输入框存在；填入合法值并点击"保存并测试"（桩掉试连）后文件被写入；
  试连返回失败时既不覆盖原有配置、也不凭空创建首个配置；写盘失败时给出提示且原文件不变；
  恢复默认失败时给出提示且不清空输入框。
- 分析进行中：触发器与弹窗内的"保存并测试""恢复默认"都置灰。
- 就绪检查：`check_llm_ready(settings)` 传参时不回读文件；不传参时以本地配置为准。
- `save()` 自身也校验：绕过界面直接调用（脚本、测试）写不进非法配置。
- 并发保存：用 `ThreadPoolExecutor` 并发保存，`future.result()` 让线程里的异常浮出来，
  断言八次全部成功、最终文件是完整一致的某一套、无残留 `.tmp`。
- 锁的语义：删除与保存共用同一把锁——保存正卡在替换阶段时，删除必须等它退出临界区；
  两个任务都经 `future.result()` 收结果，用于放行的 `Event` 在 `finally` 里置位，失败不遗留线程。
- 写盘失败：`os.replace` 抛错时原文件逐字节不变，`.tmp` 被清掉；写流本身失败时两个文件都不留；
  预存一个宽权限 `.tmp` 会被收紧到 `0600`（`os.fchmod` 在 Windows 上不存在，测试注入后验证）。
- 本轮冻结：`model_config.frozen()` 用 `ContextVar`，`react.stream`、`app.workspace.run_analysis`、
  CLI 两个入口各冻结一次，嵌套复用；并发线程互不可见；退出后恢复读最新配置。
  冻结期内另一个标签页换 Key，报错仍按**开跑时那一个** Key 脱敏——工作台（入库的 error）、
  CLI（stderr）、评测（报告文件）三个出口各有回归。
- 流与上下文的边界：`next()` 之后调用方的 `active()` 仍是自己的状态；另一轮读到最新配置；
  同线程两轮交替推进各保持自己的设置；提前停止 / 显式 `close()` / 流内部异常 / 调用方
  处理事件时抛异常 / 外层 `frozen()` 先退出后 `close()` / 在另一层上下文里 `close()`——
  都不留残留，也不抛跨上下文 token 错。这些用例都持有生成器引用，不靠 GC 碰巧通过。

回归：`python -m pytest -q tests` 全绿（实现后为 452 项，其中本功能 80 项）。

## 6. 风险

- **保存的 Key 是明文**：`.gitignore` 精确排除该文件；界面上掩码显示；不写日志。
- **试连与真实调用可能不一致**：部分代理对 `max_tokens` 或流式支持有差异，试连只发普通
  非流式请求。若试连失败但真实调用可用，用户可以再点一次保存前先"恢复默认"。
- **DuckDB 无关**：配置是文件，不涉及会话库，不影响并发。
