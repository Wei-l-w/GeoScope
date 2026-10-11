# 修复与本地验收（2026-10-11）

本记录对应功能开发阶段的本地验收：未调用模型 API，当时尚未提交或推送远程仓库。

## 修复内容

- RAG 索引：检查格式、scikit-learn 版本和实际检索能力；旧版本、损坏或未拟合缓存自动从仓库重建，原子替换保存。
- 航迹：过滤空值、非有限数及非法坐标，保留时间顺序和起终点，严格不超过 500 点；单点输出合法 Point；检查 days 参数。
- SQL：DuckDB 原生 AST 校验单条查询、非递归 CTE、业务表和计算函数，阻止表函数、外部文件、网络和动态 SQL；限制结果行数并明确标记截断；执行超时中断。
- ReAct：跨轮次累计同工具连续调用次数，第三次起真正阻断并回填工具消息；修复静默 CLI 返回 None。
- 页面验收：入口改为 GeoAgent.py，会话库隔离；CI 配置增加七页初始化检查。

## 本次验证

| 检查 | 结果 | 口径 |
| --- | --- | --- |
| 全部离线回归 | 99/99 通过 | 模型替身、内存/临时数据库及本地仓库，无 API |
| 七个页面初始化 | 7/7 通过 | Streamlit AppTest，不等于全部浏览器交互通过 |
| 已保存 SQL 兼容性 | 16/16 通过 | 在真实仓库中比较原 SQL 和受保护执行结果；不是新一轮模型准确率评测 |
| 语法编译、git diff --check | 通过 | 本地代码检查 |
| 真实 RAG 缓存恢复 | 通过 | 重建 3,135 个知识块，检索返回 3 个命中，再次加载复用缓存 |

原索引备份：

`G:\玩具项目-数据整合系统\data\agent_output\backups\rag_index.before_repair_20261011_132432.pkl`

重建后的索引仍在 `data/rag_index.pkl`，使用当前 scikit-learn 1.4.2。原数据仓库没有修改。

## 复现

在项目目录用 PowerShell 执行：

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'
$env:PYTHONUTF8='1'
python -m pytest tests/ -q -p no:cacheprovider --basetemp data/agent_output/pytest_regression_20261011
python scripts/smoke_test.py
python -m compileall -q agent app scripts tests
git diff --check
```

SQL 默认返回上限为 1000 行，可用 `GEOSQL_MAX_ROWS` 配置；执行阶段默认 30 秒后中断，可用 `GEOSQL_QUERY_TIMEOUT` 配置，模型调用、解析及初始化不计入该时限。

本次未进行在线模型端到端复测、远程 CI 或 Docker 验证。页面仍有原有 Streamlit `use_container_width` 弃用提示，未产生初始化异常。历史 `eval/report.md` 保持原样。
