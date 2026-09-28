"""统一设计系统：主题（深/浅切换）、配色、CSS、KPI 卡片、图例、地图与图表封装。

主题机制：
- THEMES 定义每套主题的全部 CSS 变量（背景、卡片、文字、边框等）
- setup() 在侧栏渲染主题切换器，并按所选主题注入变量
- 浅色主题额外注入 _LIGHT_CSS 覆盖 Streamlit 原生深色控件
- 图表（style_fig）与地图（deck）根据当前主题自动切换模板/底图
"""
import pandas as pd
import pydeck as pdk
import streamlit as st

# ---- 数据源标准色（地图图层 / 图表 / 图例保持一致）----
ACCENT = "#22d3ee"          # 主色: 青
C_AIS = [34, 211, 238]      # AIS   青
C_GDELT = [251, 191, 36]    # GDELT 琥珀
C_ACLED = [248, 113, 113]   # ACLED 红
PLOTLY_WAY = ["#22d3ee", "#fbbf24", "#f87171", "#a78bfa", "#34d399", "#fb923c", "#60a5fa"]

FONT_STACK = '"Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", "PingFang SC", sans-serif'
MONO_STACK = '"Cascadia Code", Consolas, "JetBrains Mono", monospace'

# ACLED 事件类型配色
ACLED_TYPE_COLORS = {
    "Battles": [248, 113, 113],
    "Explosions/Remote violence": [251, 146, 60],
    "Protests": [52, 211, 153],
    "Riots": [167, 139, 250],
    "Violence against civilians": [96, 165, 250],
}

THEME_KEY = "ui_theme"
DEFAULT_THEME = "暮蓝柔夜"

# ---- 主题变量表：新增主题只需加一组变量。下拉顺序即字典顺序（按亮度排列）----
THEMES = {
    "极昼浅色": {
        "bg-body": "#eef2f9",
        "bg-grad": "linear-gradient(165deg, #f7f9fd 0%, #eef2fa 36%, #e8ecf7 58%, #eef1f9 80%, #f4f6fb 100%)",
        "glow-tr": "rgba(34,211,238,.20)",
        "glow-bl": "rgba(139,92,246,.15)",
        "glow-br": "rgba(236,72,153,.11)",
        "glow-bc": "rgba(16,185,129,.09)",
        "band": ("linear-gradient(118deg, transparent 28%, rgba(34,211,238,.08) 42%, "
                 "rgba(139,92,246,.08) 54%, rgba(236,72,153,.05) 66%, transparent 80%)"),
        "grid": "rgba(15,23,42,.045)",
        "card-1": "rgba(255,255,255,.90)",
        "card-2": "rgba(246,249,255,.96)",
        "sb-1": "#fbfcff",
        "sb-2": "#eff2f9",
        "tx-hero": "#0f172a",
        "tx-1": "#0f172a",
        "tx-2": "#334155",
        "tx-3": "#64748b",
        "tx-4": "#8593a8",
        "line": "rgba(15,23,42,.14)",
        "chip-bg1": "rgba(255,255,255,.85)",
        "chip-bg2": "rgba(241,245,252,.92)",
        "chip-tx": "#475569",
        "nav-tx": "#475569",
        "nav-active": "#0e7490",
        "brand-tx": "#0f172a",
        "map-bg": "#dfe6f0",
        "scroll": "#c3cddd",
        "glow-pct": "14%",
    },
    # 柔和深色（默认）：中性灰蓝底 + 弱环境光，比深空极光明亮、比浅色沉稳
    "暮蓝柔夜": {
        "bg-body": "#1b2231",
        "bg-grad": "linear-gradient(165deg, #232c3f 0%, #202839 34%, #1e2534 55%, #1c2331 78%, #1a2030 100%)",
        "glow-tr": "rgba(34,211,238,.13)",
        "glow-bl": "rgba(139,92,246,.14)",
        "glow-br": "rgba(236,72,153,.10)",
        "glow-bc": "rgba(16,185,129,.08)",
        "band": ("linear-gradient(118deg, transparent 28%, rgba(34,211,238,.05) 42%, "
                 "rgba(139,92,246,.07) 54%, rgba(236,72,153,.04) 66%, transparent 80%)"),
        "grid": "rgba(148,163,184,.05)",
        "card-1": "rgba(46,57,80,.78)",
        "card-2": "rgba(30,38,55,.93)",
        "sb-1": "#212a3d",
        "sb-2": "#1a2233",
        "tx-hero": "#eef2f8",
        "tx-1": "#eceff5",
        "tx-2": "#c5cedd",
        "tx-3": "#96a3ba",
        "tx-4": "#71809a",
        "line": "rgba(148,163,184,.22)",
        "chip-bg1": "rgba(54,65,90,.62)",
        "chip-bg2": "rgba(33,41,59,.86)",
        "chip-tx": "#acb9ce",
        "nav-tx": "#c5cedd",
        "nav-active": "#7ee8f7",
        "brand-tx": "#e8f7fb",
        "map-bg": "#161d2b",
        "scroll": "#2e3a54",
        "glow-pct": "26%",
    },
    # 高对比科幻深色：已整体提亮一档（背景/卡片/边框/辅助文字），减少压抑感
    "深空极光": {
        "bg-body": "#10182e",
        "bg-grad": "linear-gradient(165deg, #10182e 0%, #121838 34%, #151438 55%, #111632 78%, #0e142a 100%)",
        "glow-tr": "rgba(34,211,238,.19)",
        "glow-bl": "rgba(139,92,246,.22)",
        "glow-br": "rgba(236,72,153,.17)",
        "glow-bc": "rgba(16,185,129,.12)",
        "band": ("linear-gradient(118deg, transparent 28%, rgba(34,211,238,.08) 42%, "
                 "rgba(139,92,246,.11) 54%, rgba(236,72,153,.07) 66%, transparent 80%)"),
        "grid": "rgba(148,163,184,.045)",
        "card-1": "rgba(37,52,84,.85)",
        "card-2": "rgba(18,27,48,.94)",
        "sb-1": "#131c3a",
        "sb-2": "#0f1528",
        "tx-hero": "#f1f5f9",
        "tx-1": "#f4f7fb",
        "tx-2": "#cbd5e1",
        "tx-3": "#97a8c1",
        "tx-4": "#76889f",
        "line": "rgba(148,163,184,.20)",
        "chip-bg1": "rgba(39,53,84,.68)",
        "chip-bg2": "rgba(19,29,50,.88)",
        "chip-tx": "#adc0d8",
        "nav-tx": "#ccd8e9",
        "nav-active": "#7ee8f7",
        "brand-tx": "#e8f7fb",
        "map-bg": "#0e1526",
        "scroll": "#263452",
        "glow-pct": "32%",
    },
}

_CSS = """
<style>
/* ================= 基础 ================= */
html, body, [data-testid="stAppViewContainer"] * { font-family: %(font)s; }
/* Material 图标字体必须保留，否则图标显示为字面文字 */
[data-testid="stIconMaterial"], span[class*="material-symbols"],
[data-testid="stExpanderToggleIcon"] {
  font-family: "Material Symbols Rounded" !important;
}

/* 背景放在固定定位层：只绘制一次，滚动时不重绘（性能关键）。颜色全部走主题变量。
   Streamlit 各层容器背景全部透明化，否则会挡住主题背景层。 */
.stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {
  background: transparent !important;
}
body { background: var(--bg-body) !important; }
body::before {
  content: ""; position: fixed; inset: 0; z-index: -1; pointer-events: none;
  background:
    radial-gradient(1100px 560px at 10%% -8%%, color-mix(in srgb, var(--page-accent, #22d3ee) 20%%, transparent), transparent 58%%),
    radial-gradient(1200px 600px at 92%% -10%%, var(--glow-tr), transparent 60%%),
    radial-gradient(1000px 620px at -14%% 76%%, var(--glow-bl), transparent 60%%),
    radial-gradient(1000px 560px at 112%% 88%%, var(--glow-br), transparent 58%%),
    radial-gradient(760px 460px at 55%% 118%%, var(--glow-bc), transparent 60%%),
    var(--band),
    linear-gradient(var(--grid) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid) 1px, transparent 1px),
    var(--bg-grad);
  background-size: auto, auto, auto, auto, auto, auto, 44px 44px, 44px 44px, auto;
}

/* 隐藏 Streamlit 原生痕迹（不能隐藏整个 stToolbar，侧栏展开按钮在里面） */
#MainMenu, footer, [data-testid="stDecoration"], [data-testid="stStatusWidget"],
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stToolbarActions"] { display: none !important; }
[data-testid="stHeader"] { background: transparent !important; pointer-events: none; }
[data-testid="stHeader"] * { pointer-events: auto; }
[data-testid="stExpandSidebarButton"] {
  background: var(--chip-bg2) !important; border: 1px solid color-mix(in srgb, var(--page-accent) 45%%, transparent) !important;
  border-radius: 8px !important; box-shadow: 0 0 12px color-mix(in srgb, var(--page-accent) 25%%, transparent);
  margin: 6px 0 0 6px;
}
[data-testid="stExpandSidebarButton"] span, [data-testid="stExpandSidebarButton"] svg {
  color: var(--nav-active) !important; fill: var(--nav-active) !important;
}

.block-container { padding-top: 2.6rem; padding-bottom: 2.5rem; max-width: 1560px; }

/* 滚动条与选区 */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--scroll); border-radius: 8px; }
::selection { background: color-mix(in srgb, var(--page-accent) 30%%, transparent); }

/* ================= 页头 ================= */
.gis-header { display: flex; justify-content: space-between; align-items: flex-end;
  gap: 16px; flex-wrap: wrap; margin-bottom: .1rem; }
.gis-header .t {
  font-size: 1.85rem; font-weight: 750; line-height: 1.15; letter-spacing: .01em;
  background: linear-gradient(92deg, var(--tx-hero) 22%%,
    color-mix(in srgb, var(--page-accent, #22d3ee) 60%%, var(--tx-hero)) 58%%,
    var(--page-accent, #22d3ee) 92%%);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
.gis-header .s { color: var(--tx-3); font-size: .875rem; margin-top: .3rem; letter-spacing: .015em; }
.gis-header .chips { display: flex; gap: 8px; flex-wrap: wrap; padding-bottom: .35rem; }
.chip {
  display: inline-flex; align-items: center; gap: 7px;
  font-size: .72rem; letter-spacing: .1em; color: var(--chip-tx); text-transform: uppercase;
  background: linear-gradient(160deg, var(--chip-bg1), var(--chip-bg2));
  border: 1px solid var(--line); border-radius: 999px;
  padding: 5px 13px; font-variant-numeric: tabular-nums;
}
.chip.live { color: #10b981; border-color: rgba(16,185,129,.4); }
.chip.live i {
  width: 7px; height: 7px; border-radius: 50%%; background: #10b981; display: inline-block;
  box-shadow: 0 0 8px 1px rgba(16,185,129,.8); animation: pulse 2.2s ease-in-out infinite;
}
@keyframes pulse { 0%%,100%% { opacity: 1; } 50%% { opacity: .35; } }
.gis-rule {
  height: 2px; border: 0; margin: .85rem 0 1.25rem; border-radius: 2px;
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--page-accent, #22d3ee) 60%%, transparent),
    color-mix(in srgb, var(--page-accent, #22d3ee) 14%%, transparent) 45%%, transparent 85%%);
  box-shadow: 0 0 12px color-mix(in srgb, var(--page-accent, #22d3ee) 28%%, transparent);
}

/* ================= KPI 卡片 ================= */
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr));
  gap: 13px; margin: .3rem 0 1.15rem; }
.kpi {
  --kc: var(--page-accent, #22d3ee);
  background: linear-gradient(158deg, var(--card-1), var(--card-2));
  border: 1px solid var(--line); border-radius: 12px;
  padding: 15px 17px 13px; position: relative; overflow: hidden;
  box-shadow: 0 14px 34px -22px rgba(2,6,23,.5), inset 0 1px 0 rgba(255,255,255,.05);
  transition: transform .16s ease, border-color .16s ease, box-shadow .16s ease;
}
.kpi:hover {
  transform: translateY(-2px);
  border-color: color-mix(in srgb, var(--kc) 55%%, transparent);
  box-shadow: 0 18px 40px -20px rgba(2,6,23,.55), 0 0 22px -8px var(--kc);
}
.kpi::before {
  content: ""; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, var(--kc), transparent 78%%);
}
.kpi::after {
  content: ""; position: absolute; top: -34px; right: -34px; width: 92px; height: 92px;
  background: radial-gradient(circle, color-mix(in srgb, var(--kc) 16%%, transparent), transparent 70%%);
  pointer-events: none;
}
.kpi .l { color: var(--tx-3); font-size: .74rem; letter-spacing: .13em; text-transform: uppercase; }
.kpi .v { color: var(--tx-1); font-size: 1.62rem; font-weight: 700; margin-top: 4px;
  font-family: %(mono)s; font-variant-numeric: tabular-nums; letter-spacing: -.01em;
  text-shadow: 0 0 22px color-mix(in srgb, var(--kc) var(--glow-pct), transparent); }
.kpi .c { color: var(--tx-4); font-size: .76rem; margin-top: 3px; font-variant-numeric: tabular-nums; }

/* ================= 图例 ================= */
.legend { display: flex; flex-wrap: wrap; gap: 8px 10px; margin: .6rem 0 .3rem; }
.legend .item {
  display: inline-flex; align-items: center; gap: 7px; color: var(--tx-2); font-size: .78rem;
  background: var(--chip-bg1); border: 1px solid var(--line);
  border-radius: 999px; padding: 4px 12px 4px 9px;
}
.legend .sw { width: 9px; height: 9px; border-radius: 50%%; display: inline-block;
  background: var(--sc); box-shadow: 0 0 8px 1px var(--sc); }

/* ================= 面板标题 ================= */
.panel-t {
  display: flex; align-items: center; gap: 9px;
  color: var(--tx-2); font-size: .98rem; font-weight: 650; letter-spacing: .02em;
  margin: 1.05rem 0 .55rem;
}
.panel-t::before {
  content: ""; width: 4px; height: 15px; border-radius: 2px;
  background: linear-gradient(180deg, var(--page-accent, #22d3ee),
    color-mix(in srgb, var(--page-accent, #22d3ee) 55%%, var(--bg-body)));
  box-shadow: 0 0 10px color-mix(in srgb, var(--page-accent, #22d3ee) 58%%, transparent);
}
.panel-t::after {
  content: ""; flex: 1; height: 1px;
  background: linear-gradient(90deg, var(--line), transparent 70%%);
}

/* ================= 侧栏 ================= */
[data-testid="stSidebar"] {
  background:
    radial-gradient(420px 300px at 0%% 0%%, color-mix(in srgb, var(--page-accent, #22d3ee) 12%%, transparent), transparent 70%%),
    radial-gradient(380px 420px at 0%% 100%%, var(--glow-bl), transparent 70%%),
    linear-gradient(180deg, var(--sb-1) 0%%, var(--sb-2) 100%%);
  border-right: 1px solid var(--line);
}
/* 品牌区：伪元素挂在导航最顶部 */
[data-testid="stSidebarNav"] { display: flex; flex-direction: column; padding-top: .3rem; }
[data-testid="stSidebarNav"]::before {
  order: -2; content: "GEOSCOPE";
  color: var(--brand-tx); font-weight: 800; letter-spacing: .24em; font-size: .95rem;
  padding: 12px 16px 2px 58px; min-height: 34px; display: flex; align-items: center;
  background: url("data:image/svg+xml,%%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%%3E%%3Ccircle cx='16' cy='16' r='14' fill='none' stroke='%%2322d3ee' stroke-opacity='.55'/%%3E%%3Ccircle cx='16' cy='16' r='8.5' fill='none' stroke='%%2322d3ee' stroke-opacity='.28'/%%3E%%3Ccircle cx='16' cy='16' r='2.6' fill='%%2322d3ee'/%%3E%%3Cline x1='16' y1='16' x2='26' y2='7' stroke='%%2322d3ee' stroke-width='1.6' stroke-linecap='round' stroke-opacity='.8'/%%3E%%3Ccircle cx='24.5' cy='8.5' r='2' fill='%%237ff3ff'/%%3E%%3C/svg%%3E")
    no-repeat 16px 10px / 32px 32px;
  filter: drop-shadow(0 0 8px rgba(34,211,238,.25));
}
[data-testid="stSidebarNav"]::after {
  order: -1; content: "红海危机时空情报平台";
  color: var(--tx-4); font-size: .66rem; letter-spacing: .04em; white-space: nowrap;
  padding: 0 12px 12px 58px; margin-bottom: .5rem;
  border-bottom: 1px solid var(--line);
}

/* 侧栏导航 */
[data-testid="stSidebarNav"] a {
  border-radius: 8px; margin: 1px 0; transition: background .15s ease;
}
[data-testid="stSidebarNav"] a:hover { background: color-mix(in srgb, var(--page-accent) 9%%, transparent); }
[data-testid="stSidebarNav"] a[aria-current="page"] {
  background: linear-gradient(90deg, color-mix(in srgb, var(--page-accent) 16%%, transparent),
    color-mix(in srgb, var(--page-accent) 4%%, transparent));
  border-left: 2px solid var(--page-accent);
}
[data-testid="stSidebarNav"] a span { color: var(--nav-tx); font-size: .88rem; }
[data-testid="stSidebarNav"] a[aria-current="page"] span { color: var(--nav-active); font-weight: 600; }

/* 侧栏控件 */
[data-testid="stSidebar"] h2 { color: var(--tx-3); font-size: .78rem !important;
  letter-spacing: .16em; text-transform: uppercase; }
[data-testid="stSidebar"] label { color: var(--tx-2) !important; font-size: .82rem !important; }
[data-baseweb="tag"] {
  background: color-mix(in srgb, var(--page-accent, #22d3ee) 13%%, transparent) !important;
  border: 1px solid color-mix(in srgb, var(--page-accent, #22d3ee) 42%%, transparent) !important;
  border-radius: 6px !important;
}
[data-baseweb="tag"] span {
  color: color-mix(in srgb, var(--page-accent, #22d3ee) 45%%, var(--tx-1)) !important;
}

/* ================= 地图容器（HUD 边角）================= */
[data-testid="stDeckGlJsonChart"] {
  position: relative; border: 1px solid var(--line); border-radius: 12px;
  overflow: hidden; background: var(--map-bg);
  box-shadow: 0 18px 44px -26px rgba(2,6,23,.5);
}
[data-testid="stDeckGlJsonChart"]::before,
[data-testid="stDeckGlJsonChart"]::after {
  content: ""; position: absolute; width: 22px; height: 22px; z-index: 5; pointer-events: none;
}
[data-testid="stDeckGlJsonChart"]::before {
  top: 8px; left: 8px;
  border-top: 2px solid color-mix(in srgb, var(--page-accent, #22d3ee) 78%%, transparent);
  border-left: 2px solid color-mix(in srgb, var(--page-accent, #22d3ee) 78%%, transparent);
  border-top-left-radius: 6px;
  filter: drop-shadow(0 0 5px color-mix(in srgb, var(--page-accent, #22d3ee) 62%%, transparent));
}
[data-testid="stDeckGlJsonChart"]::after {
  bottom: 8px; right: 8px;
  border-bottom: 2px solid color-mix(in srgb, var(--page-accent, #22d3ee) 78%%, transparent);
  border-right: 2px solid color-mix(in srgb, var(--page-accent, #22d3ee) 78%%, transparent);
  border-bottom-right-radius: 6px;
  filter: drop-shadow(0 0 5px color-mix(in srgb, var(--page-accent, #22d3ee) 62%%, transparent));
}

/* ================= 表格 / 其他组件 ================= */
[data-testid="stDataFrame"] {
  border: 1px solid var(--line); border-radius: 12px; overflow: hidden;
  box-shadow: 0 12px 30px -24px rgba(2,6,23,.45);
}
[data-testid="stExpander"] {
  border: 1px solid var(--line) !important; border-radius: 10px !important;
  background: linear-gradient(160deg, var(--card-1), var(--card-2)) !important;
  margin-bottom: 6px;
}
[data-testid="stExpander"] summary:hover { color: var(--nav-active) !important; }
[data-testid="stAlert"] {
  border: 1px solid var(--line); border-radius: 10px;
  background: linear-gradient(160deg, var(--card-1), var(--card-2));
}
hr:not(.gis-rule) { border-color: var(--line) !important; }

/* ================= 对话组件（GeoAgent 页） ================= */
/* 聊天气泡：接入主题卡片色，避免默认深色字配深底 */
[data-testid="stChatMessage"] {
  background: linear-gradient(160deg, var(--card-1), var(--card-2));
  border: 1px solid var(--line); border-radius: 12px;
  padding: 6px 14px; margin-bottom: 10px;
  box-shadow: 0 12px 30px -24px rgba(2,6,23,.45);
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] :is(p, li, span, td, th) {
  color: var(--tx-1);
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] :is(h1, h2, h3, h4, strong) {
  color: var(--tx-hero) !important;
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] :is(th, td) {
  border-color: var(--line);
}
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] a { color: var(--nav-active); }
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] code {
  background: var(--chip-bg2); color: var(--tx-1);
  border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px;
}

/* 代码块（工具参数 / 返回内容 / SQL） */
[data-testid="stCodeBlock"], [data-testid="stCodeBlock"] pre,
[data-testid="stCode"] pre, pre {
  background: color-mix(in srgb, var(--bg-body) 55%%, #000 8%%) !important;
  border: 1px solid var(--line) !important; border-radius: 8px !important;
}
[data-testid="stCodeBlock"] code, [data-testid="stCodeBlock"] pre *,
[data-testid="stCode"] code, [data-testid="stCode"] pre *, pre code, pre * {
  color: var(--tx-1) !important;
  font-family: %(mono)s !important; font-size: .78rem !important;
}

/* 提示条（思考中 / 警告）：默认浅蓝字在深色卡片上不可读 */
[data-testid="stAlert"] { border: 1px solid var(--line); border-radius: 10px;
  background: linear-gradient(160deg, var(--card-1), var(--card-2)); }
[data-testid="stAlert"] :is(p, span, div) { color: var(--tx-1) !important; }
[data-testid="stAlert"] svg { fill: var(--nav-active) !important; }

/* 工具状态卡片（st.status 基于 expander，文字颜色需显式指定） */
[data-testid="stExpander"] summary :is(span, p, div) { color: var(--tx-1); }
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] :is(p, span) { color: var(--tx-2); }

/* 对话输入框 */
[data-testid="stChatInput"] > div,
[data-testid="stChatInput"] [data-baseweb="textarea"], [data-testid="stChatInput"] [data-baseweb="base-input"] {
  background: var(--chip-bg2) !important;
  border: 1px solid var(--line) !important; border-radius: 12px !important;
}
[data-testid="stChatInput"] textarea {
  background: transparent !important; color: var(--tx-1) !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: var(--tx-4) !important; }
[data-testid="stChatInput"] button { color: var(--nav-active) !important; }
[data-testid="stChatInput"] button svg, [data-testid="stChatInput"] svg { fill: var(--nav-active) !important; }

/* 按钮（示例问题等次要按钮接入主题卡片色） */
[data-testid="stButton"] button {
  background: linear-gradient(160deg, var(--chip-bg1), var(--chip-bg2)) !important;
  border: 1px solid var(--line) !important; border-radius: 10px !important;
  color: var(--tx-1) !important;
}
[data-testid="stButton"] button p, [data-testid="stButton"] button span {
  color: var(--tx-1) !important;
}
[data-testid="stButton"] button:hover {
  border-color: color-mix(in srgb, var(--page-accent) 55%%, transparent) !important;
  color: var(--nav-active) !important;
}
[data-testid="stButton"] button:hover p, [data-testid="stButton"] button:hover span {
  color: var(--nav-active) !important;
}

/* 新闻条目 */
.news-item {
  border-left: 2px solid color-mix(in srgb, var(--page-accent, #22d3ee) 48%%, transparent);
  padding: 3px 0 4px 11px;
  margin-bottom: 10px; transition: border-color .15s ease, background .15s ease;
  border-radius: 0 6px 6px 0; }
.news-item:hover { border-left-color: var(--page-accent, #22d3ee);
  background: color-mix(in srgb, var(--page-accent, #22d3ee) 6%%, transparent); }
.news-item .m { color: var(--tx-4); font-size: .72rem; letter-spacing: .04em;
  font-variant-numeric: tabular-nums; }
.news-item .h { color: var(--tx-2); font-size: .86rem; line-height: 1.45; margin-top: 1px; }
</style>
""" % {"font": FONT_STACK, "mono": MONO_STACK}

# 浅色主题下覆盖 Streamlit 原生深色控件（config.toml 主题无法运行时切换）
_LIGHT_CSS = """
<style>
[data-testid="stAppViewContainer"] { color: #334155; }
[data-testid="stMarkdownContainer"] :is(p, li) { color: #334155; }
h1, h2, h3, [data-testid="stHeading"] * { color: #0f172a !important; }
[data-testid="stWidgetLabel"] p { color: #475569 !important; }
[data-testid="stCaptionContainer"] p, [data-testid="stCaptionContainer"] span { color: #64748b !important; }

/* 输入类控件 */
[data-baseweb="input"], [data-baseweb="input"] input, [data-baseweb="textarea"] textarea,
[data-baseweb="select"] > div, [data-testid="stNumberInputContainer"],
[data-testid="stDateInput"] [data-baseweb="input"] {
  background: #ffffff !important; color: #0f172a !important;
  border-color: rgba(15,23,42,.2) !important;
}
[data-baseweb="select"] input { color: #0f172a !important; }
[data-baseweb="select"] div { color: #1e293b; }
[data-testid="stNumberInput"] button { background: #eef2f9 !important; color: #0f172a !important; }

/* 下拉弹层 / 日历 / 菜单 */
[data-baseweb="popover"] > div, [data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] li, [data-baseweb="calendar"], [data-baseweb="calendar"] div {
  background-color: #ffffff !important; color: #0f172a !important;
}
[data-baseweb="popover"] li:hover { background-color: #eef2f9 !important; }
[data-baseweb="calendar"] [aria-selected="true"] { background-color: #0e7490 !important; color: #fff !important; }

/* 单选 / 复选 / 滑块 / 展开条 */
[data-testid="stRadio"] label p, [data-testid="stCheckbox"] label p { color: #334155 !important; }
[data-testid="stSliderThumbValue"] { color: #0e7490 !important; }
[data-testid="stSlider"] [data-testid="stTickBarMin"], [data-testid="stSlider"] [data-testid="stTickBarMax"] { color: #64748b !important; }
[data-testid="stExpander"] summary span, [data-testid="stExpander"] summary p { color: #334155 !important; }
[data-testid="stExpander"] [data-testid="stMarkdownContainer"] p { color: #334155; }

/* 链接与分页控件 */
a, a span { color: #0e7490; }

/* ---- 浅色主题：按钮（基础主题为 dark，未覆盖则深色底+深色字） ---- */
[data-testid="stButton"] button {
  background: #ffffff !important; color: #0f172a !important;
  border: 1px solid rgba(15,23,42,.22) !important;
  box-shadow: 0 1px 2px rgba(15,23,42,.06) !important;
}
[data-testid="stButton"] button p, [data-testid="stButton"] button span {
  color: #0f172a !important;
}
[data-testid="stButton"] button:hover {
  border-color: #0e7490 !important; color: #0e7490 !important;
}
[data-testid="stButton"] button:hover p, [data-testid="stButton"] button:hover span {
  color: #0e7490 !important;
}
[data-testid="stButton"] button[kind="primary"],
[data-testid="stButton"] button[kind="primary"] p {
  background: #0e7490 !important; color: #ffffff !important;
}

/* ---- 浅色主题：对话输入框（容器与文本域都必须压白底） ---- */
[data-testid="stChatInput"], [data-testid="stChatInput"] > div,
[data-testid="stChatInput"] [data-baseweb="textarea"], [data-testid="stChatInput"] [data-baseweb="base-input"] {
  background: #ffffff !important;
}
[data-testid="stChatInput"] textarea {
  background: #ffffff !important; color: #0f172a !important;
}
[data-testid="stChatInput"] textarea::placeholder { color: #8593a8 !important; }
[data-testid="stChatInput"] button { background: #eef2f9 !important; }
[data-testid="stChatInput"] button svg, [data-testid="stChatInput"] svg { fill: #0e7490 !important; color: #0e7490 !important; }

/* ---- 浅色主题：展开条/状态卡片的图标与次要文字 ---- */
[data-testid="stExpander"] svg { fill: #475569 !important; }
</style>
"""

_TOOLTIP_DARK = {
    "backgroundColor": "rgba(10, 16, 31, .94)",
    "color": "#dbe4f0",
    "fontSize": "12px",
    "fontFamily": FONT_STACK,
    "border": "1px solid rgba(34,211,238,.35)",
    "borderRadius": "8px",
    "boxShadow": "0 10px 30px rgba(0,0,0,.55)",
    "padding": "8px 12px",
}
_TOOLTIP_LIGHT = {
    "backgroundColor": "rgba(255, 255, 255, .97)",
    "color": "#0f172a",
    "fontSize": "12px",
    "fontFamily": FONT_STACK,
    "border": "1px solid rgba(14,116,144,.35)",
    "borderRadius": "8px",
    "boxShadow": "0 10px 30px rgba(15,23,42,.18)",
    "padding": "8px 12px",
}


def _current_theme() -> str:
    return st.session_state.get(THEME_KEY, DEFAULT_THEME)


def _is_light() -> bool:
    return _current_theme() == "极昼浅色"


def setup(title: str, accent: str = ACCENT) -> None:
    """每个页面第一个调用：页面配置 + 主题切换器 + 注入主题变量与 CSS。

    accent: 页面主题色。页头渐变、面板竖条、KPI 默认色、地图边角、
            背景环境光等都会跟随该颜色。
    """
    st.set_page_config(page_title=f"{title} · GeoScope", layout="wide",
                       initial_sidebar_state="expanded")
    # 关键：切换页面时 Streamlit 会清掉"仅属于控件"的状态导致主题回退，
    # 渲染前自赋值一次可把它固定为跨页面持久的会话状态
    if THEME_KEY in st.session_state:
        st.session_state[THEME_KEY] = st.session_state[THEME_KEY]
    with st.sidebar:
        st.selectbox("界面主题", list(THEMES.keys()), key=THEME_KEY)
    theme_vars = THEMES[_current_theme()]
    var_lines = "".join(f"--{k}: {v};" for k, v in theme_vars.items())
    st.markdown(
        f"<style>:root {{ --page-accent: {accent}; {var_lines} }}</style>",
        unsafe_allow_html=True,
    )
    st.markdown(_CSS, unsafe_allow_html=True)
    if _is_light():
        st.markdown(_LIGHT_CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str = "", chips: list | None = None) -> None:
    """页头：标题 + 副标题 + 右侧状态徽章。chips: [文本] 或 [(文本, 'live')]"""
    chip_html = ""
    if chips:
        parts = []
        for c in chips:
            if isinstance(c, tuple):
                text, kind = c
                dot = "<i></i>" if kind == "live" else ""
                parts.append(f'<span class="chip {kind}">{dot}{text}</span>')
            else:
                parts.append(f'<span class="chip">{c}</span>')
        chip_html = f'<div class="chips">{"".join(parts)}</div>'
    st.markdown(
        f'<div class="gis-header"><div><div class="t">{title}</div>'
        f'<div class="s">{subtitle}</div></div>{chip_html}</div><hr class="gis-rule">',
        unsafe_allow_html=True,
    )


def kpi_row(items: list) -> None:
    """items: [(标签, 数值, 说明)] 或 [(标签, 数值, 说明, 颜色hex)]

    不传颜色时自动跟随页面主题色。
    """
    cards = []
    for it in items:
        label, value, cap = it[0], it[1], it[2]
        style = f' style="--kc:{it[3]}"' if len(it) > 3 else ""
        cards.append(
            f'<div class="kpi"{style}><div class="l">{label}</div>'
            f'<div class="v">{value}</div><div class="c">{cap}</div></div>'
        )
    st.markdown(f'<div class="kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)


def legend(items: list) -> None:
    """items: [(名称, [r,g,b])]"""
    chips = "".join(
        f'<span class="item"><span class="sw" style="--sc:rgb({c[0]},{c[1]},{c[2]})"></span>{n}</span>'
        for n, c in items
    )
    st.markdown(f'<div class="legend">{chips}</div>', unsafe_allow_html=True)


def panel(title: str) -> None:
    st.markdown(f'<div class="panel-t">{title}</div>', unsafe_allow_html=True)


def deck(layers, lat: float, lon: float, zoom: float, tooltip=None, height: int = 560) -> None:
    """跟随主题切换底图（深色 Carto Dark / 浅色 Carto Positron）的 deck.gl 地图。"""
    style = _TOOLTIP_LIGHT if _is_light() else _TOOLTIP_DARK
    tt = {"text": tooltip, "style": style} if isinstance(tooltip, str) else tooltip
    st.pydeck_chart(
        pdk.Deck(
            map_style="light" if _is_light() else "dark",
            initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom, pitch=0),
            layers=layers,
            tooltip=tt,
        ),
        height=height,
    )


def chart(fig, height: int = 320) -> None:
    """渲染 Plotly 图表。必须 theme=None，否则 Streamlit 会用自带深色主题
    覆盖 style_fig 的浅色样式，导致浅色模式下图表文字不可读。"""
    st.plotly_chart(style_fig(fig, height), use_container_width=True, theme=None)


def style_fig(fig, height: int = 320):
    """Plotly 图表跟随主题的统一风格。"""
    light = _is_light()
    fig.update_layout(
        template="plotly_white" if light else "plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#334155" if light else "#b9c6da", size=12,
                  family="Segoe UI, Microsoft YaHei UI, sans-serif"),
        colorway=PLOTLY_WAY,
        margin=dict(l=0, r=0, t=14, b=0),
        height=height,
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", yanchor="bottom", y=1.02,
                    title_text=""),
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,.97)" if light else "rgba(10,16,31,.95)",
            bordercolor="rgba(14,116,144,.4)" if light else "rgba(34,211,238,.4)",
            font=dict(color="#0f172a" if light else "#dbe4f0", size=12,
                      family="Segoe UI, Microsoft YaHei UI, sans-serif"),
        ),
        bargap=0.25,
    )
    grid = "rgba(15,23,42,.09)" if light else "rgba(148,163,184,.1)"
    zero = "rgba(15,23,42,.16)" if light else "rgba(148,163,184,.18)"
    fig.update_xaxes(gridcolor=grid, zerolinecolor=zero, linecolor=zero)
    fig.update_yaxes(gridcolor=grid, zerolinecolor=zero, linecolor=zero)
    return fig
