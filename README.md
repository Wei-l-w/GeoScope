# 数据整合可视化平台

整合 AIS 船舶动态、GDELT / ACLED 地缘政治事件、新闻文本等多源数据，统一存入 DuckDB 数据仓库，并通过 Streamlit 提供地图与图表可视化。

## 技术栈

- 存储/查询：DuckDB（单文件 `data/warehouse.duckdb`，千万行级查询流畅）
- 前端：Streamlit + pydeck（deck.gl 地图）+ Plotly
- 部署：Docker / docker-compose

## 快速开始（本机）

```powershell
# 1. 安装依赖
pip install -r requirements.txt

# 2. 生成仿真样例数据（真实数据到位前先跑通全流程）
python scripts/generate_sample_data.py

# 3. 入库
python -m ingest.load ais   data/raw/ais_sample.csv
python -m ingest.load gdelt data/raw/gdelt_sample.csv
python -m ingest.load acled data/raw/acled_sample.csv
python -m ingest.load news  data/raw/news_sample.csv

# 4. 启动
streamlit run app/Home.py
```

浏览器访问 http://localhost:8501

## 导入真实数据（原文件只读、不移动）

> 本仓库**不包含任何真实数据**。AIS / ACLED / GDELT 原始数据需自行获取，放在本地任意路径后按下面的命令入库。

`ingest/mappings.py` 已按常见格式配置好（含 `~` 分隔无表头 AIS、单位换算、类型码翻译）。入库命令：

```powershell
python -m ingest.load ais        '<AIS动态数据目录>\*.csv'
python -m ingest.load ais_static '<AIS静态数据目录>\*.csv'
python -m ingest.load gdelt      '<GDELT导出文件>.csv'
python -m ingest.load acled      '<ACLED事件文件>.csv'
python -m ingest.load news       '<新闻正文抓取结果>.jsonl'
```

要点：

- 支持通配符批量导入（88 个每日 AIS 文件一条命令入库）；重复导入按主键自动去重，可随时增量补数。
- 换其他格式的数据时，只需修改 [`ingest/mappings.py`](ingest/mappings.py) 中对应源的 `columns` 映射和 `read_options` 读取选项，不用改表结构和页面。
- AIS 动态数据单位换算已内置：经纬度 ÷600000、航速/航向 ÷10、UTC 秒转时间戳、哨兵值(511/1023等)转 NULL。

数据源与目标表对应：

| 数据源 | 目标表 | 说明 |
| --- | --- | --- |
| ais | ais_positions | 动态位置（~ 分隔无表头，字段定义见数据目录 PDF） |
| ais_static | ais_ships | 船舶静态档案（船名/类型/尺寸），页面按 mmsi 关联 |
| gdelt | gdelt_events | 标准 GDELT 列 + EventName 增强列 |
| acled | acled_events | ACLED 官方标准字段 |
| news | news_articles | ACLED 原文回填 JSONL，带 related_event_id 关联事件 |

## 服务器部署（团队访问）

服务器装好 Docker 后：

```bash
docker compose up -d --build
```

团队通过 `http://服务器IP:8501` 访问。数据入库在服务器上执行：

```bash
docker compose exec app python scripts/generate_sample_data.py   # 或把真实数据放入 data/raw/
docker compose exec app python -m ingest.load ais data/raw/ais_sample.csv
```

`data/` 目录通过卷挂载持久化，重建容器不丢数据。

## 项目结构

```
├── app/                # Streamlit 应用（Home.py + pages/ 五个页面）
├── ingest/             # 入库脚本；mappings.py 是字段映射配置（适配你的数据只改这里）
├── db/schema.sql       # 数据仓库表结构
├── scripts/            # 样例数据生成
├── data/raw/           # 原始数据文件放这里（已 gitignore）
└── data/warehouse.duckdb  # DuckDB 仓库（入库后自动生成）
```
