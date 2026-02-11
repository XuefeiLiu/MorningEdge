# MorningEdge - Design Documentation | 设计文档

## English Version

### 1. Design Philosophy
MorningEdge is a decision-support platform designed for the modern investor who seeks to understand the "Why" behind market movements. The UI adheres to a high-end, minimal aesthetic inspired by Robinhood, utilizing a deep black background (#000000) with high-contrast "Volt" green (#CCFF00) as the primary action color. The layout is optimized to reduce cognitive load while maximizing the visibility of causal links between news events and price action.

### 2. Interface Breakdown

#### A. Login Screen
*   **Visual Side (Left)**: Uses a bold, high-impact typography style. It emphasizes the mission: "Invest in Narratives."
*   **Form Side (Right)**: A clean, minimal entry point focused on a frictionless user experience.

#### B. Dashboard & Navigation
*   **Global Header**: Fixed at the top, providing quick access to the "Narrative" (primary) and "Account" (placeholder) tabs.
*   **List Toggle**: A prominent dropdown allows users to switch between "My Portfolio" and "My Watch List."
*   **Stock Grid**: Stocks are displayed as cards with "Mini Visualizers"—real-time sparklines that provide an immediate sense of momentum. Each card shows **Market Open Prediction** only when overnight prediction data exists (e.g. ~1.5% ↑, ~2.0% ↓, Neutral); when there is no prediction, the card shows nothing in that area.
*   **Deprecation**: `story_type` (e.g. SHORT FILING) and storyline title fallback are deprecated for the stock card display; the frontend no longer shows these.
*   **Search & Add**: A sleek, animated search bar allows users to quickly add new tickers to their active lists.

#### C. Stock Detail View
*   **Left Column (Market Feed & Filters)**: Provides granular control over news categories (Stock, Industry, Macro, Sentiment) and timeframes.
*   **Right Column (Tabbed Content)**:
    *   **Timeline Tab**: The heart of the app. It displays chronological events linked to the stock.
    *   **Price Impact Tab**: A specialized chart that maps news events directly onto the price curve to visualize correlation.

### 3. Causal Narrative Engine
The standout feature of MorningEdge. 
*   **Causal Narrative OFF (A-Type)**: Displays raw, fragmented news events in a chronological vertical timeline.
*   **Causal Narrative ON (B-Type)**: Activates the "Synthetic Insight" mode. AI aggregates multiple related news events into high-level "Causal Narratives," filtering noise and highlighting structural market shifts.

### 4. Detail Overlays (The Retrospective Modals)
Clicking an event on either timeline triggers a detailed overlay that covers the right 39% of the screen.
*   **A-Type (Individual News)**: Includes the original transmission text, AI Insight Analysis, a Sentiment Directional Bias bar, and a User Intelligence Log (comment box).
*   **B-Type (Synthetic Insight)**: Retains white titles for consistency. It deconstructs the narrative into "Constituent Evidence" (the raw news events), provides a Narrative Synthesis, displays a Historical Causal Impact bar, and includes a Portfolio Strategy Log.

---

## 中文版本

### 1. 设计理念
MorningEdge 是一款为希望理解市场波动背后“为什么”的现代投资者设计的决策支持平台。UI 遵循受 Robinhood 启发的高端极简美学，采用纯黑背景 (#000000) 和高对比度的“伏特绿” (#CCFF00) 作为主操作色。布局旨在减轻认知负荷，同时最大限度地提高新闻事件与价格走势之间因果联系的可见性。

### 2. 界面拆解

#### A. 登录界面
*   **视觉侧（左侧）**: 采用大胆、高冲击力的排版风格，强调产品使命：“投资于叙事。”
*   **表单侧（右侧）**: 简洁、极简的入口，专注于无摩擦的用户体验。

#### B. 仪表盘与导航
*   **全局页眉**: 固定在顶部，提供对“叙事”（主功能）和“账户”（占位）选项卡的快速访问。
*   **列表切换**: 显眼的下拉菜单允许用户在“我的投资组合”和“我的自选股”之间切换。
*   **股票网格**: 股票以卡片形式展示，配有“微型可视化器”——即时走势图，提供直观的动量感。
*   **已弃用**: `story_type`（如 SHORT FILING）及 storyline 标题回退已弃用，前端不再展示。
*   **搜索与添加**: 精美的动画搜索栏，允许用户快速向当前列表添加新股票。

#### C. 股票详情页
*   **左栏（市场信息流与过滤器）**: 提供对新闻类别（个股、行业、宏观、情绪）和时间范围的细粒度控制。
*   **右栏（标签内容）**:
    *   **时间轴标签 (Timeline)**: 应用的核心，按时间顺序显示与股票相关的事件。
    *   **价格影响标签 (Price Impact)**: 专用图表，将新闻事件直接映射到价格曲线上，以可视化相关性。

### 3. 因果叙事引擎 (Causal Narrative)
MorningEdge 的核心亮点。
*   **因果叙事关闭 (A型)**: 在垂直时间轴中显示原始、碎片化的新闻事件。
*   **因果叙事开启 (B型)**: 激活“合成洞察”模式。AI 将多个相关的新闻事件聚合为高层级的“因果叙事”，过滤杂音并突出结构性的市场转变。

### 4. 详情浮窗（复盘弹窗）
点击任何时间轴上的事件都会触发一个覆盖右侧区域 39% 的详情浮窗。
*   **A型（单条新闻）**: 包含新闻原文、AI 洞察分析、情绪定向偏差条以及用户情报日志（评论框）。
*   **B型（合成洞察）**: 标题保持白色以维持视觉一致性。它将叙事拆解为“关键证据”（原始新闻事件），提供叙事合成分析，展示历史因果影响条，并包含投资组合策略日志。