# GeoAgent · 自然语言驱动的空间分析智能体

> **English**: A spatial-reasoning AI agent built on LangChain. Ask geospatial questions in natural language — it performs intent recognition, task decomposition, Function Calling, Text-to-GeoSQL generation and renders results on an interactive map (GeoJSON / deck.gl), delivering a "what-you-ask-is-what-you-see" experience.

![Python](https://img.shields.io/badge/python-3.12+-blue)
![CI](https://github.com/Wei-l-w/GeoScope/actions/workflows/ci.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-green)
![Eval](https://img.shields.io/badge/GeoSQL%20exec%20accuracy-16%2F16-brightgreen)

以 **2023 下半年红海危机** 为垂直场景：AIS 船舶动态（3760 万行）· ACLED 冲突事件（LLM 增强标注）· GDELT 全球舆情 · 新闻原文，统一入 DuckDB 空间数据仓库，由 Agent 提供对话式分析入口。

---

## Demo

<!-- 待补：录制 demo GIF 放 docs/demo.gif，展示 缓冲区分析 / 船舶航迹 / 知识库问答 三个场景 -->

| 缓冲区分析 | 船舶航迹 | 知识库问答 |
| --- | --- | --- |
| "曼德海峡周边 150km 内发生了多少起事件？" | "MMSI 668116204 最近 30 天走了什么路线？" | "银河领袖号事件有什么背景？" |

运行效果：左栏流式展示 Agent 的"思考 → 调用工具 → 返回结果"全过程（类 Claude Code），右栏地图在几何结果产出的瞬间即时渲染（缓冲区圆 / 事件点 / 航迹线）。

## 架构

```
用户问题（中/英文）
   │
   ▼
┌─────────────────────────────────────────────┐
│ ReAct Agent（LangChain bind_tools 原生循环）  │
│  Planner：意图识别 / 任务拆解 / 工具选择      │
│  Critic ：SQL 报错自纠正 + 同工具调用熔断     │
└─────────────────────────────────────────────┘
   │ Function Calling（5 个插件化工具）
   ├─ geocode          地名 → 经纬度（Nominatim + 内置地名库兜底）
   ├─ buffer_analysis  缓冲区分析（SQL 下推）→ GeoJSON
   ├─ ship_track       船舶航迹（自动抽稀 ≤500 点）→ GeoJSON
   ├─ query_database   Text-to-GeoSQL（schema linking + 错题本 few-shot + 自纠正）
   └─ knowledge_search RAG 知识库（3100+ 知识块，附出处）
   │
   ▼
DuckDB Spatial 仓库（5 表） + TF-IDF 向量索引（可换稠密后端）
   │
   ▼
Streamlit + deck.gl：GeoJSON 即时上图，"所问即所得"
```

## 能力映射（为什么是这个项目）

| 能力点 | 实现 | 代码位置 |
| --- | --- | --- |
| Agent 架构 / 意图识别 / 任务拆解 / Function Calling | LangChain ReAct 主循环，流式事件输出，工具调用熔断 | `agent/react.py` |
| GIS 工具链封装为 Tools/Plugins | 缓冲区 / 叠置统计 / 地理编码 / 航迹，点面运算全部 SQL 下推（千万行秒级） | `agent/tools.py` |
| Text-to-SQL / GeoSQL 准确率优化 | schema linking + 检索式 few-shot + 报错自纠正；**16 条执行准确率评测 16/16=100%**（[报告](eval/report.md)） | `agent/geosql.py` `agent/eval.py` |
| 空间知识库 RAG | 新闻正文切块 + 事件描述 → 3100+ 知识块，余弦 top-k 带引用；嵌入后端抽象可插拔 | `agent/rag.py` |
| GeoJSON / deck.gl 可视化交互 | 三类几何结果（圆/点/线）即时上图，流式工具调用可视化，多轮指代对话，会话持久化 | `app/GeoAgent.py` |

## 快速开始

```bash
pip install -r requirements.txt

# 配置任意 OpenAI 兼容服务（DeepSeek / 通义 / 官方均可），写入项目根 .env：
#   OPENAI_API_KEY=sk-...
#   OPENAI_BASE_URL=https://api.deepseek.com
#   MODEL_NAME=deepseek-chat

# 1. 生成仿真样例数据并入库（真实数据到位前先跑通全流程）
python scripts/generate_sample_data.py
python -m ingest.load ais   data/raw/ais_sample.csv
python -m ingest.load gdelt data/raw/gdelt_sample.csv
python -m ingest.load acled data/raw/acled_sample.csv
python -m ingest.load news  data/raw/news_sample.jsonl

# 2. 构建 RAG 索引
python -m agent.rag --rebuild

# 3. 启动（GeoAgent 即首屏）
streamlit run app/GeoAgent.py
```

CLI 模式（无界面，脚本化调用）：

```bash
python -m agent.chat "曼德海峡周边150公里内有哪些高风险事件？"
python -m agent.chat --direct --csv result.csv "苏伊士运河区域的油轮统计"
```

Docker 部署：`docker compose up -d --build`，访问 `http://localhost:8501`。

## GeoSQL 评测（可复现）

业界口径（Spider / BIRD）的**执行准确率**评测：不比 SQL 文本，比预测 SQL 与金标 SQL 的执行结果集（浮点 0.1 容差、多重集合比较）。

```bash
python -m agent.eval                 # 全量 16 条
python -m agent.eval --tag distance  # 按类别跑
python -m agent.eval --out eval/report.md
```

- 评测集 `eval/geosql_eval.jsonl`：16 条手工标注，覆盖区域 / 距离 / 聚合 / 排名 / 多表关联 / 时间窗 6 类空间查询；
- 当前成绩：**16/16 = 100%**（平均约 20s/条，含 3760 万行表的关联查询）；
- 评测驱动的迭代实例：首轮暴露「投影列不严格 / LIMIT 缺确定性排序」→ 加强生成规则 + 补例题后修复，完整对比见 [eval/report.md](eval/report.md)。

## 导入真实数据（原文件只读、不移动）

> 本仓库**不包含任何真实数据**。AIS / ACLED / GDELT 原始数据需自行获取，放在本地任意路径后按下面的命令入库。

`ingest/mappings.py` 已按常见格式配置好（含 `~` 分隔无表头 AIS、单位换算、类型码翻译）：

```powershell
python -m ingest.load ais        '<AIS动态数据目录>\*.csv'
python -m ingest.load ais_static '<AIS静态数据目录>\*.csv'
python -m ingest.load gdelt      '<GDELT导出文件>.csv'
python -m ingest.load acled      '<ACLED事件文件>.csv'
python -m ingest.load news       '<新闻正文抓取结果>.jsonl'
```

要点：

- 支持通配符批量导入（88 个每日 AIS 文件一条命令入库）；重复导入按主键自动去重，可随时增量补数；
- 换其他格式的数据时，只需修改 `ingest/mappings.py` 中对应源的 `columns` 映射和 `read_options`，不用改表结构和页面；
- AIS 动态数据单位换算已内置：经纬度 ÷600000、航速/航向 ÷10、UTC 秒转时间戳、哨兵值转 NULL。

数据源与目标表对应：

| 数据源 | 目标表 | 说明 |
| --- | --- | --- |
| ais | ais_positions | 动态位置（~ 分隔无表头） |
| ais_static | ais_ships | 船舶静态档案，页面按 mmsi 关联 |
| gdelt | gdelt_events | 标准 GDELT 列 + EventName 增强列 |
| acled | acled_events | ACLED 官方字段 + 红海危机专题 LLM 标注 |
| news | news_articles | 原文回填 JSONL，related_event_id 关联事件 |

## 测试与 CI

```bash
pytest tests/ -q    # 18 条离线单测，无需 LLM
```

GitHub Actions（`.github/workflows/ci.yml`）：checkout → 安装依赖 → 样例数据建库 → compileall + pytest，推送即跑。

## 设计决策（FAQ）

- **为什么 DuckDB 而不是 PostGIS？** 单文件零运维，spatial 扩展提供 `ST_*` 函数，开发期体验远好；表结构与 SQL 均为标准空间 SQL，生产化时可平滑迁移到 PostgreSQL/PostGIS（改连接层 + `ST_` 函数方言即可）。
- **RAG 为什么用 TF-IDF？** 检索接口按「embed → 向量 → 余弦 top-k」标准抽象，当前后端为 TF-IDF 稀疏向量（无 embedding 服务端点的环境可跑）；换 OpenAI/本地稠密模型只需替换嵌入后端，检索与工具层不动。
- **跨语言检索**：语料为英文，Agent 自动把中文问题改写为英文关键词再检索（LLM query rewriting），不引入额外翻译模型。

## Roadmap

- [ ] 多智能体扩展：Critic 拆分为独立结果校验 Agent（当前以自纠正回路内嵌）
- [ ] 路径规划工具：接入 OSRM / osmnx，封装为 Agent Tool（接口预留）
- [ ] 滚动摘要式多轮记忆（当前为最近 N 轮全量注入）
- [ ] PostGIS 后端切换指南与适配层

## 项目结构

```
├── app/GeoAgent.py     # GeoAgent 首屏（对话 + 流式工具可视化 + 即时上图）
├── app/pages/          # 总览 / AIS / ACLED / 时空叠加 / 新闻检索 / 全球背景参考
├── agent/              # 智能体核心
│   ├── react.py        # ReAct 主循环（流式事件）
│   ├── tools.py        # 5 个 GIS/查数/RAG 工具（插件化注册）
│   ├── geosql.py       # Text-to-GeoSQL 链（schema linking + 自纠正）
│   ├── fewshot.py      # GeoSQL 错题本（检索式 few-shot）
│   ├── rag.py          # RAG 知识库（嵌入后端抽象）
│   ├── sessions.py     # 会话持久化（独立 duckdb）
│   └── eval.py         # 执行准确率评测器
├── ingest/             # 入库脚本；mappings.py 是字段映射配置
├── eval/               # 评测集 + 报告
├── tests/              # 离线单测（无需 LLM）
├── db/schema.sql       # 数据仓库表结构
└── data/               # DuckDB 仓库与索引（gitignore，不入库）
```

## License

[MIT](LICENSE)
