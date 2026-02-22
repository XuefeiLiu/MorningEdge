# MorningEdge 代码库评审报告

---

## 1. 代码质量和最佳实践检查

*（由 code-quality-reviewer 撰写）*

### 1.1 Python 类型注解覆盖率

**整体评分：8/10 — 良好**

整个后端代码库对类型注解的使用较为一致，Pydantic 模型为请求/响应提供了严格的验证。

**优点：**
- `models.py` 中所有核心模型均使用了 Pydantic，字段类型明确：
  ```python
  # backend/models.py:46-56
  class NewsItem(BaseModel):
      id: str
      ticker: str
      published_at: datetime
      title: str
      summary: Optional[str] = None
      url: Optional[str] = None
      source: str
      created_at: datetime = Field(default_factory=datetime.utcnow)
      collector: str
      embedding: Optional[List[float]] = None
  ```
- `embedding_service.py` 中函数签名完整，返回类型清晰：
  ```python
  # backend/services/embedding_service.py:43-47
  async def get_embeddings(
      self,
      texts: List[str],
      timeout: Optional[float] = None
  ) -> Optional[np.ndarray]:
  ```
- FastAPI 路由使用了 `response_model=` 参数，自动生成文档和响应校验。

**问题：**
- 部分存储查询函数（`backend/storage/` 下）缺少返回类型注解。
- `Dict[str, Any]` 在多处使用，可以用更具体的 Pydantic 模型替代（尤其在 `stories.py` 中处理 Supabase 返回行时）。
- `frontend/types.ts` 中的 `NewsItem` 接口与后端 `models.py::NewsItem` 存在字段不一致（前端有 `sentiment`、`category`，后端没有），缺少自动同步机制。

---

### 1.2 错误处理模式

**整体评分：6.5/10 — 中等**

错误处理存在明显的不一致性，部分位置有安全风险。

**重大问题一：裸 `except:` 子句（3 处）**

```python
# backend/services/collectors/massive.py:183
try:
    error_body = e.response.json()
    logger.error(f"Massive API 400 error for {symbol}: {error_body}")
except:  # ❌ 捕获了所有异常，包括 KeyboardInterrupt 和 SystemExit
    logger.error(f"Massive API 400 error for {symbol}: {e.response.text}")

# backend/services/collectors/massive.py:192（同文件第二处）
# backend/services/collectors/marketaux.py:170（同类问题）
```

应改为 `except (ValueError, JSONDecodeError) as json_err:` 或至少 `except Exception as json_err:`，避免意外捕获系统退出信号。

**重大问题二：API 错误详情泄露（多处）**

```python
# backend/routers/briefing.py:39
raise HTTPException(status_code=500, detail=f"Failed to generate briefing: {str(e)}")

# backend/routers/stories.py:117
raise HTTPException(status_code=500, detail=str(e))

# backend/routers/stories.py:340
raise HTTPException(status_code=500, detail=str(e))
```

将内部异常的字符串直接暴露给 API 响应存在安全风险——可能泄露内部路径、数据库 schema、第三方 API URL 等敏感信息。正确做法是在服务器端记录详细日志，对客户端返回通用错误信息：

```python
# ✅ 建议做法
logger.error("Error generating briefing: %s", e, exc_info=True)
raise HTTPException(status_code=500, detail="内部服务错误，请稍后重试")
```

**优点：**
- `news_aggregator.py` 的 `asyncio.TimeoutError` 和 `CancelledError` 处理正确，超时后返回空列表而非崩溃。
- `embedding_service.py` 的指数退避重试逻辑（最多 5 次，解析 429 响应头中的等待时间）设计良好。
- `CancelledError` 在 `news_aggregator.py:110` 处被正确重新抛出。

---

### 1.3 代码风格一致性

**整体评分：9/10 — 优秀**

整体遵循 PEP 8 规范，命名风格统一。

**优点：**
- 函数/变量命名统一使用 `snake_case`，类名使用 `PascalCase`。
- 所有公共函数均有文档字符串（docstring），格式一致。
- `logger = logging.getLogger(__name__)` 在每个模块顶部声明，位置一致。
- 导入组织规范，先标准库、后第三方、后本地模块。

**小问题：**
- 部分长函数（如 `stories.py` 中的 `_create_custom_story_impl`，约 150 行）逻辑密集，内联注释稀少，可读性有所下降。
- `stories.py` 中的 Supabase 查询逻辑分散在路由层而非存储层，与项目的 `*_query.py` 分层模式不一致。

---

### 1.4 安全实践

**整体评分：7/10 — 良好，存在改进空间**

**优点：**
- ✅ 所有 API 密钥通过环境变量管理（`config.py:12-20`），未硬编码。
- ✅ Pydantic 自动进行输入校验，防止畸形请求。
- ✅ `news.py` 中的查询参数使用了范围限制：`limit: int = Query(100, ge=1, le=1000)`。
- ✅ Supabase 使用 SDK，无手动 SQL 拼接，规避注入风险。
- ✅ Ask 接口实现了 IP 级别的速率限制（`ask_limits.py`）和并发控制（semaphore）。

**问题：**

1. **CORS 配置宽泛**（`main.py:47-48`）：
   ```python
   allow_methods=["*"],
   allow_headers=["*"],
   ```
   生产环境应明确指定允许的方法和请求头，而非全部开放。

2. **登录机制无身份验证**（`frontend/App.tsx:13-15`）：
   ```typescript
   const handleLogin = (username: string) => {
     setUser({ isLoggedIn: true, username });
   };
   ```
   登录逻辑仅在前端维护状态，无后端 token 验证，API 端点实际上对所有访问者开放。

3. **IP 获取方式不健壮**（`stories.py:493`）：
   ```python
   client_ip = http_request.client.host if http_request.client else "unknown"
   ```
   在反向代理（Nginx/CloudFlare）后面时，`client.host` 可能是代理 IP，应优先读取 `X-Forwarded-For` 或 `X-Real-IP` 请求头。

---

### 1.5 异步处理

**整体评分：9/10 — 优秀**

**优点：**
- `news_aggregator.py:96-99` 中使用 `asyncio.gather` 并行执行多个收集器任务，配以全局超时（40 秒上限）：
  ```python
  results = await asyncio.wait_for(
      asyncio.gather(*tasks, return_exceptions=True),
      timeout=global_timeout
  )
  ```
- 每个收集器有独立超时（`_collect_from_source`：一般 30 秒，NewsNow 90 秒），防止单个慢源阻塞整体。
- `embedding_service.py` 使用 `AsyncOpenAI` 客户端，与 FastAPI 异步运行时兼容。
- `asyncio.CancelledError` 在所有关键路径上被正确地重新抛出。

**小问题：**
- `_get_ask_semaphore()` 采用延迟初始化方式（`stories.py:30-35`），在并发启动场景下可能有竞态条件，建议在应用启动时初始化。

---

### 1.6 数据库查询效率

**整体评分：7/10 — 良好，有优化空间**

**优点：**
- Supabase 客户端封装为单例（`supabase_client.py`），避免重复连接。
- 存储层遵循 `*_save.py` / `*_query.py` 分层模式，职责清晰。
- Bigint ID 使用确定性哈希生成（`_string_id_to_bigint`），避免自增 ID 的分布式问题。

**问题：**

1. **`news_aggregator.py:77-78` 中的循环内重复查询**：
   ```python
   for collector in collectors:
       config = news_registry.get_config(collector.name)  # 每次循环都查询
   ```
   建议在循环前将所有 config 缓存为字典，或在 `news_registry` 中维护索引。

2. **`_deduplicate` 方法的 O(n²) 复杂度**（`news_aggregator.py:244-249`）：
   ```python
   for item in lang_items:
       for seen_title in seen_titles:  # 内层循环随数量线性增长
           similarity = SequenceMatcher(None, title_lower, seen_title).ratio()
   ```
   当收集到数百条新闻时，性能会显著下降。建议考虑 MinHash LSH 或 TF-IDF + 余弦相似度替代。

3. **`stories.py` 中部分查询未检查 `result.data` 为 `None`**：
   虽然大部分地方使用了 `result.data or []` 模式，但 Supabase 查询失败时 `result` 本身可能为 `None`，导致 `AttributeError`。

---

### 1.7 React/TypeScript 前端代码质量

**整体评分：7/10 — 良好**

**组件设计：**

`App.tsx`（34 行）结构极简洁，职责单一。`api.ts` 使用泛型参数 `<T>` 保证类型安全：
```typescript
// frontend/api.ts:11
export async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T>
```

**重大问题：StockDetail.tsx（2328 行）严重过大**

该组件包含了价格图表、故事线列表、文件引用、新闻过滤器等多个独立功能，违反了单一职责原则。`NarrativeCluster` 接口定义了 15+ 个字段（`StockDetail.tsx:21-47`）、本地类型、常量、工具函数，导致单文件极难维护。建议至少拆分为：
- `PriceChart.tsx` — 价格历史图表
- `StorylineList.tsx` — 故事线列表和筛选
- `FilingCitation.tsx` — SEC 文件引用展示
- `NarrativeCluster.tsx` — 叙事聚类卡片

**`api.ts` 缺失超时控制和重试逻辑：**
```typescript
// frontend/api.ts:12
const res = await fetch(`${API_BASE}${path}`, options);
// ❌ 无超时设置 — 网络请求可能无限挂起
// ❌ 无重试逻辑 — 瞬时网络错误直接失败
```

**类型安全：**
- `types.ts` 使用了严格的 TypeScript 接口和字面量联合类型，整体良好。
- `frontend/types.ts::NewsItem` 与后端 `backend/models.py::NewsItem` 字段不匹配，实际在 `StockDetail.tsx` 中使用了本地的 `NarrativeCluster` 类型，存在类型维护负担。

**Dashboard.tsx 硬编码初始股票：**
```typescript
// frontend/components/Dashboard.tsx:64
const INITIAL_PORTFOLIO: Stock[] = [
  { symbol: 'AAPL', name: 'Apple Inc.', price: 0, ... },
  // 7 支股票硬编码
];
```

---

### 1.8 测试覆盖率和质量

**整体评分：3/10 — 严重不足**

| 测试文件 | 测试内容 | 问题 |
|---------|---------|------|
| `test_api.py` | `/health`、`/watchlist` GET/PUT（3 个测试） | 覆盖面极窄 |
| `test_clustering.py` | `_connected_components` 算法（8 个测试） | 是最好的示范，但仅覆盖一个函数 |
| `test_config.py` | 配置验证 | 未详查 |
| `test_helpers.py` | 工具函数 | 未详查 |
| `test_elasticsearch_rag.py` | RAG 检索 | 未详查 |

**主要问题：**
- 26,000+ 行后端代码，估计覆盖率 **< 5%**。
- 核心业务逻辑（新闻收集器、LLM 过滤器、夜间管道、宏观摘要）完全没有单元测试。
- 前端无任何测试（无 Jest/Vitest、无 React Testing Library）。
- 缺少集成测试验证端到端流程（收集 → 过滤 → 嵌入 → 聚类 → 存储）。
- `conftest.py` 的 mock 设计良好，为扩展测试打下了基础。

---

### 1.9 代码重复和可维护性

**整体评分：7.5/10**

**优点：**
- 收集器基类减少了 15+ 收集器中的重复代码。
- 过滤器工厂模式统一管理多种过滤器。
- 存储层 `*_query.py` / `*_save.py` 模式分离读写职责。

**问题：**
- `stories.py` 路由文件中多处函数内局部 import `from backend.storage.supabase_client import get_supabase_client`（共 6 处以上），建议提至模块顶层。
- `_create_custom_story_impl`（约 150 行，`stories.py:508-659`）函数过长，应提取宏观处理、RAG 检索、LLM 调用为独立函数。
- 前端 `StockDetail.tsx` 中 `formatTimestampLocal` 等工具函数内嵌在组件文件中，应移至公共工具模块。

---

### 1.10 总体评分与关键改进建议

| 维度 | 评分 | 关键问题 |
|------|------|---------|
| 类型注解 | 8/10 | 存储层部分函数缺返回类型 |
| 错误处理 | 6.5/10 | 裸 except（3 处）+ 错误信息泄露 |
| 代码风格 | 9/10 | 总体优秀，长函数内注释偏少 |
| 安全实践 | 7/10 | CORS 宽泛、无后端认证、IP 获取不健壮 |
| 异步处理 | 9/10 | 优秀，asyncio 使用规范 |
| 数据库查询 | 7/10 | O(n²) 去重、循环内重复查询 |
| 前端组件 | 7/10 | StockDetail 严重过大（2328 行） |
| 前端类型安全 | 8/10 | TypeScript 使用规范，api.ts 缺超时 |
| 测试覆盖 | 3/10 | 覆盖率 <5%，核心逻辑无测试 |
| **综合评分** | **7/10** | 架构扎实，错误处理和测试是主要短板 |

**高优先级改进（建议立即修复）：**
1. **修复裸 `except:` 子句** — `massive.py:183,192`、`marketaux.py:170`
2. **修复 API 错误信息泄露** — `briefing.py:39`、`stories.py:117,340` 等，记录详细日志但返回通用消息
3. **拆分 `StockDetail.tsx`** — 2328 行单文件不可维护
4. **为 `api.ts` 添加超时控制** — 使用 `AbortController` 防止请求无限挂起

**中优先级改进（下一迭代）：**
5. 为核心业务逻辑添加单元测试（收集器、LLM 过滤器、嵌入服务）
6. 优化 `_deduplicate` 的 O(n²) 算法
7. 将 `stories.py` 中的数据库查询逻辑下沉到存储层
8. 在生产 CORS 配置中明确指定允许的方法和请求头
9. 为后端 API 添加认证中间件（Bearer token 或 session cookie）

---

## 2. 文档完整性检查

### 概述
本部分对 MorningEdge 代码库的文档完整性进行了全面审查，涵盖项目文档、API 文档、代码注释、配置文档、部署文档和前端组件文档等方面。

### 已有文档

#### 1. **项目主文档**
- ✅ **CLAUDE.md** - 项目开发指南（评分：**9/10**）
  - 包含项目概述、快速命令、架构说明、关键模式
  - 详细说明了后端/前端结构、数据库 ID 模式、收集器模式、时区处理、RAG 检索等
  - 提供了测试和 CI/CD 信息
  - 优点：信息完整、组织清晰、覆盖面广
  - 不足：缺少常见问题解答（FAQ）、故障排除指南

#### 2. **前端文档**
- ✅ **frontend/START.md** - 快速启动指南（评分：**8/10**）
  - 清晰的入门步骤、环境配置、常见问题
  - 优点：新手友好、步骤明确
  - 不足：缺少高级配置说明、性能优化建议

- ✅ **frontend/Design.md** - 设计文档（评分：**8/10**）
  - 详细的 UI 设计理念、界面拆解、色彩方案、交互流程（英文+中文）
  - 包含因果叙事引擎说明、浮窗设计
  - 优点：视觉设计清晰、用户流程详细
  - 不足：缺少前端架构说明、组件关系图、状态管理说明

#### 3. **后端管道文档**
- ✅ **backend/pipeline/README.md** - 管道概述（评分：**7/10**）
  - 介绍夜间管道、关键模块、数据库表、配置
  - 优点：结构清晰、表格整理好
  - 不足：算法细节不够深入

- ✅ **backend/pipeline/overnight_pipeline/README.md** - 夜间管道详解（评分：**9/10**）
  - 极其详细的管道算法说明
  - 包含 7 个关键步骤：数据存储、文章窗口、嵌入、聚类、LLM 处理、持久化、提交文件链接、长故事处理
  - 包含运行命令示例、依赖说明
  - 优点：算法细节完整、伪代码清晰、可运维性强
  - 不足：缺少性能基准和故障排除

#### 4. **脚本文档**
- ✅ **backend/scripts/README_scripts.md** - 脚本使用指南（评分：**8/10**）
  - 覆盖故事线、清理、去重、嵌入、宏观等脚本
  - 每个脚本都有使用示例、参数说明
  - 优点：命令示例完整、参数清晰、支持 --dry-run
  - 不足：缺少脚本性能说明、故障恢复指南

#### 5. **配置文档**
- ✅ **.env.example** - 环境变量示例（评分：**8/10**）
  - 覆盖数据库、OpenAI、数据源、Elasticsearch、文件、管道、Ask 端点等
  - 每个变量都有说明、默认值
  - 优点：分类清晰、注释详细
  - 不足：缺少值范围验证说明、依赖关系说明（哪些变量是互斥的）

#### 6. **.cursor 相关文档**
- ✅ **.cursor/agents/frontend-backend-sync.md** - 前端-后端同步代理（评分：**8/10**）
- ✅ **.cursor/skills/database-id-bigint/SKILL.md** - 数据库 ID 技能（评分：**8/10**）
  - 这两个文档清晰说明了 Agent 的功能和使用规则
  - 优点：指导清晰、使用模式明确
  - 不足：缺少实际使用案例

### 缺失的文档

#### 1. **根目录 README.md**（**优先级：高**）
- **当前状态**：不存在
- **需要内容**：
  - 项目简介（1-2 段）
  - 核心特性列表
  - 快速开始（链接到 CLAUDE.md）
  - 架构高级概览
  - 技术栈
  - 贡献指南
  - 许可证

#### 2. **API 文档**（**优先级：高**）
- **当前状态**：仅依赖 FastAPI 自动文档（/docs）
- **需要内容**：
  - API 端点总览（按分类）：briefing、news、stories、macro、watchlist、stocks、system
  - 认证说明
  - 请求/响应示例
  - 错误处理指南
  - 速率限制说明
  - 关键端点详解（如 GET /overnight-stories、POST /stories/ask）
  - WebSocket 说明（如果有）

#### 3. **前端架构文档**（**优先级：中**）
- **当前状态**：缺少
- **需要内容**：
  - 组件树结构
  - 状态管理方式（Context、Redux 等）
  - 路由配置说明
  - API 层使用（api.ts）
  - 国际化系统说明
  - 主要页面流程

#### 4. **数据库架构文档**（**优先级：中**）
- **当前状态**：缺少
- **需要内容**：
  - ER 图或数据库关系图
  - 关键表说明（news_articles、story、long_stories、macro_* 等）
  - 表字段和数据类型
  - 索引策略
  - pgvector 使用说明
  - 迁移历史

#### 5. **数据收集器文档**（**优先级：中**）
- **当前状态**：仅在 CLAUDE.md 中提及基础模式
- **需要内容**：
  - 15+ 数据源列表及其功能
  - 每个收集器的使用方式、错误处理
  - 添加新收集器的完整步骤
  - API 密钥配置说明

#### 6. **部署和运维文档**（**优先级：高**）
- **当前状态**：缺少
- **需要内容**：
  - 生产部署步骤（Docker、云平台）
  - 环境配置（生产、测试、开发）
  - 监控和日志策略
  - 备份和恢复流程
  - 错误告警和处理
  - 性能优化建议
  - CI/CD 流程详解（GitHub Actions）

#### 7. **故障排除指南**（**优先级：高**）
- **当前状态**：缺少
- **需要内容**：
  - 常见错误和解决方案
  - 日志分析指南
  - 数据库连接问题排查
  - API 超时/限速处理
  - 嵌入和 LLM 调用失败处理
  - Elasticsearch 相关问题

#### 8. **宏观模块深度文档**（**优先级：中**）
- **当前状态**：仅在 CLAUDE.md 中提及，backend/macro/prompt_demo.md 是示例
- **需要内容**：
  - 8 个宏观话题（FX、RATE 等）的定义
  - 知识库摄入流程
  - 宏观摘要生成算法
  - 宏观 KB RAG 检索说明
  - 配置参数说明

#### 9. **测试文档**（**优先级：中**）
- **当前状态**：缺少
- **需要内容**：
  - 测试覆盖率要求
  - 单元测试编写指南
  - 集成测试说明
  - 运行测试命令
  - Mock 数据使用

#### 10. **性能优化和基准文档**（**优先级：低**）
- **当前状态**：缺少
- **需要内容**：
  - 吞吐量基准（articles/day、stories/day）
  - 查询性能优化建议
  - 缓存策略
  - 资源使用情况

### 代码注释质量评估

#### 优点
- ✅ 关键函数有文档字符串（docstrings）
- ✅ FastAPI 路由有参数说明（description）
- ✅ 复杂算法有逐步说明（如夜间管道）

#### 不足
- ❌ 某些关键业务逻辑缺少注释（如聚类、LLM 调用逻辑）
- ❌ 前端组件缺少 JSDoc 注释
- ❌ 某些工具函数注释不足
- ❌ 复杂的 SQL 查询缺少说明

**建议**：为以下部分添加注释
- 聚类算法（T_ASSIGN、T_GRAPH 阈值的含义）
- RAG 检索逻辑
- 嵌入和相似度计算
- 长故事合并/创建逻辑

### 前端组件文档

**当前状态**：缺少组件级文档
- 未找到组件 Props、用法、示例的文档
- 建议为主要组件添加 Storybook 或注释

### 总体评分及建议

| 分类 | 现状评分 | 建议优先级 | 改进建议 |
|------|---------|----------|---------|
| **项目主文档** | 9/10 | 低 | 添加 FAQ、故障排除 |
| **前端文档** | 8/10 | 中 | 添加架构、组件说明 |
| **后端管道文档** | 9/10 | 低 | 添加性能基准 |
| **脚本文档** | 8/10 | 低 | 添加故障恢复指南 |
| **配置文档** | 8/10 | 低 | 添加依赖关系说明 |
| **API 文档** | 4/10 | **高** | 创建独立 API 文档 |
| **数据库文档** | 2/10 | **高** | 创建 ER 图和表说明 |
| **部署文档** | 1/10 | **高** | 创建部署指南 |
| **故障排除** | 1/10 | **高** | 创建故障排除指南 |
| **代码注释** | 6/10 | 中 | 增加关键逻辑的注释 |

### 总体文档完整性评分

**得分：6.5/10**

#### 优势
- ✅ 核心开发指南完整（CLAUDE.md）
- ✅ 管道算法文档详尽
- ✅ 前端 UI 设计清晰
- ✅ 环境配置说明完整

#### 主要不足
- ❌ 缺少根目录 README（第一印象）
- ❌ API 文档不独立（仅依赖 FastAPI 自动生成）
- ❌ 缺少部署运维指南（生产准备不足）
- ❌ 缺少数据库架构文档
- ❌ 缺少故障排除指南（运维风险）

### 立即行动项

**高优先级（建议在下一个迭代实施）**
1. 创建 `README.md`（项目概览、快速开始）
2. 创建 `docs/API.md`（API 端点总览和示例）
3. 创建 `docs/DEPLOYMENT.md`（部署和运维指南）
4. 创建 `docs/TROUBLESHOOTING.md`（常见问题和解决方案）
5. 创建 `docs/DATABASE.md`（数据库架构和表说明）

**中优先级（后续迭代）**
6. 创建 `docs/FRONTEND_ARCHITECTURE.md`（前端架构说明）
7. 创建 `docs/COLLECTORS.md`（数据源和收集器文档）
8. 为关键代码添加更多内联注释
9. 创建 `docs/MACRO_MODULE.md`（宏观模块详解）

**低优先级（改进）**
10. 创建 `docs/TESTING.md`（测试指南）
11. 创建 `docs/PERFORMANCE.md`（性能优化指南）
12. 为前端组件添加 JSDoc

---

## 3. 架构设计分析

*（由 architecture-reviewer 撰写）*

### 3.1 整体系统架构

MorningEdge 采用经典的前后端分离架构，后端为 Python/FastAPI，前端为 React 19 + TypeScript + Vite，数据库使用 Supabase（PostgreSQL + pgvector）。系统整体数据流如下：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        外部数据源 (15+)                              │
│  Nasdaq RSS | Alpha Vantage | NewsNow | Financial Datasets |        │
│  SEC EDGAR | FRED | Gemini | OpenAI | Alpaca | Massive | Marketaux  │
└────────────────────────────────┬────────────────────────────────────┘
                                 │ 采集（Collectors）
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       后端 (FastAPI, Port 8000)                      │
│                                                                      │
│  ┌──────────┐   ┌─────────────┐   ┌──────────────────┐             │
│  │ Routers  │──▶│  Services   │──▶│    Storage        │             │
│  │ (7个API  │   │ (业务逻辑)   │   │ (Supabase CRUD)  │             │
│  │  路由组)  │   │             │   │                  │             │
│  └──────────┘   └─────────────┘   └────────┬─────────┘             │
│                                             │                       │
│  ┌────────────────────────────────┐         │                       │
│  │   Pipeline (数据管道)           │─────────┘                       │
│  │  overnight_pipeline (推荐)     │                                 │
│  │  store_embed_data              │                                 │
│  │  long_story_service            │                                 │
│  └────────────────────────────────┘                                 │
│                                                                      │
│  ┌────────────────────────────────┐                                 │
│  │   Macro (宏观分析模块)          │                                 │
│  │  collect_raw → synthesis →     │                                 │
│  │  daily_summary → impact        │                                 │
│  └────────────────────────────────┘                                 │
└──────────────────────┬──────────────────────────────────────────────┘
                       │ REST API (JSON)
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Supabase (PostgreSQL + pgvector)                  │
│  news_articles | story | story_article_link | long_stories |         │
│  sec_filings | sec_filing_chunks | stocks | macro_raw_items |        │
│  macro_brief_* | macro_daily_summary | macro_impact_reports |        │
│  stock_prices_5min | macro_kb_chunks                                 │
└──────────────────────┬──────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│              前端 (React 19 + TypeScript + Vite, Port 3000)          │
│                                                                      │
│  App.tsx ── Login / Dashboard                                        │
│              │                                                       │
│              ├── Narrative Tab                                        │
│              │    ├── StockCard (组合/观察列表)                         │
│              │    ├── StockDetail (详情页)                             │
│              │    │    ├── TradingViewChart                           │
│              │    │    ├── StorylineTable (隔夜故事)                   │
│              │    │    └── LongStoryTimeline (长期叙事)                │
│              │    └── SearchBar (搜索)                                │
│              │                                                       │
│              ├── Macro Tab                                            │
│              │    └── MacroView (宏观简报)                             │
│              │                                                       │
│              ├── Ask Tab                                              │
│              │    └── AskChat (AI 问答)                               │
│              │                                                       │
│              └── Account Tab (待开发)                                  │
│                                                                      │
│  api.ts ── fetchJSON / postJSON (集中化 API 客户端)                    │
│  i18n/ ── 中英文国际化                                                │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 后端分层架构分析

#### 3.2.1 Routers 层（API 路由）

系统注册了 7 个 Router，职责划分清晰：

| Router | 文件 | 职责 |
|--------|------|------|
| `system` | `routers/system.py` | 健康检查、配置状态 |
| `watchlist` | `routers/watchlist.py` | 观察列表 CRUD |
| `briefing` | `routers/briefing.py` | 简报生成、AI 摘要 |
| `macro` | `routers/macro.py` | 宏观简报、日度摘要、影响报告 |
| `stories` | `routers/stories.py` | 隔夜故事、长期故事、Discover feed、Ask 问答 |
| `news` | `routers/news.py` | 股票新闻、宏观新闻查询 |
| `stocks` | `routers/stocks.py` | NASDAQ 100、实时价格、K线数据、5分钟价格 |

**优点：**
- 按业务领域划分路由，每个文件职责单一
- 使用 Pydantic `response_model` 做类型约束
- 全局 CORS 配置支持环境变量覆盖

**不足：**
- `stories.py` 承载了过多功能（660+ 行），包含隔夜故事、长期故事、Discover feed、Ask 问答、Filing 格式化，违反单一职责
- Router 层中存在较多直接数据库操作（如 `stories.py` 中大量 `supabase.table(...).select(...)` 调用），未充分利用 Service/Storage 层的抽象
- 部分 Router（如 `stories.py`）内联了完整的 LLM 调用逻辑（如 `format_filing_chunk`），应当下沉到 Service 层

#### 3.2.2 Services 层（核心业务逻辑）

```
services/
├── collectors/          # 15+ 数据源采集器
│   ├── base.py         # BaseCollector 抽象基类
│   ├── rss_collector.py # RSSCollector 继承 BaseCollector
│   ├── news_registry.py # NewsSourceRegistry (注册中心)
│   ├── alpha_vantage.py, nasdaq_rss.py, newsnow.py, ...
│   ├── gemini.py, openai.py
│   └── alpaca_market.py
├── news_filters/        # 新闻过滤器
│   ├── base.py         # NewsFilter 抽象
│   ├── keyword_filter.py
│   ├── llm_filter.py (OpenAI)
│   ├── gemini_filter.py
│   └── filter_factory.py
├── news_aggregator.py   # 多源并行聚合 + 去重
├── embedding_service.py # OpenAI text-embedding-3-small
├── briefing.py          # BriefingGenerator + TradingDirectionAnalyzer
├── ai_summaries.py      # AI 摘要生成
├── ask_limits.py        # Ask 功能限流
├── ask_extract.py       # Ask ticker/macro 提取
├── tagging.py           # Impact/Category 标签
└── filters.py           # TimeWindowFilter
```

**设计模式分析：**

1. **注册表模式 (Registry Pattern)** — `NewsSourceRegistry` 维护所有新闻源的注册中心，通过 `register()` 注册 collector + config，通过 `get_enabled_collectors()` / `get_news_collectors()` 获取可用采集器。这使得新增数据源非常简单。

2. **模板方法模式 (Template Method)** — `BaseCollector` 定义 `collect()` 和 `collect_news()` 抽象接口，各具体 Collector 实现不同的采集逻辑。`RSSCollector` 在此之上进一步提供了 RSS 解析的通用实现。

3. **工厂模式 (Factory Pattern)** — `FilterFactory` 根据配置创建不同的过滤策略（Keyword / OpenAI / Gemini），AI 过滤器失败时可降级为关键词过滤。

4. **单例模式 (Singleton)** — `EmbeddingService` 和 `news_registry` 通过全局变量实现单例，`get_embedding_service()` 保证全局唯一实例。

5. **策略模式 (Strategy Pattern)** — 新闻过滤通过 `NewsFilter` 接口支持多种过滤策略，RAG 检索支持 pgvector 和 Elasticsearch 两种后端，通过配置切换。

**优点：**
- Collector 体系设计优秀，新增数据源仅需：继承 `BaseCollector`/`RSSCollector` → 注册到 `BriefingGenerator` 和 `NEWS_SOURCES` → 在 `__init__.py` 导出
- `mark_unavailable()` 机制优雅处理数据源故障
- 并行采集 + per-collector timeout + global timeout 的三层超时保护
- Embedding 服务的 429 限流自动退避和重试策略

**不足：**
- `BriefingGenerator` 类（867 行）职责过重，既负责 Collector 注册、又管理聚合逻辑、还包含交易方向分析。应该拆分为独立的 `CollectorManager` 和 `TradingDirectionAnalyzer`
- `TradingDirectionAnalyzer` 使用简单关键词匹配做情感分析，未利用系统已有的 LLM 能力
- Collector 注册在 `BriefingGenerator.__init__` 中硬编码，应改为声明式配置 + 自动注册

#### 3.2.3 Storage 层（数据访问）

Storage 层遵循清晰的命名模式：

```
storage/
├── supabase_client.py       # Supabase 连接单例
├── news_articles_save.py    # 写入
├── news_articles_query.py   # 查询
├── news_articles_main.py    # 入口脚本
├── stocks_save.py / stocks_query.py / stocks_main.py
├── macro_*_save.py / macro_*_query.py  # 宏观各表
├── macro_id_utils.py        # ID 生成工具
├── embedding_utils.py       # 嵌入向量解析
├── elasticsearch_*.py       # ES 集成
└── watchlist_manager.py     # 本地 JSON 文件存储
```

**优点：**
- `*_save.py` / `*_query.py` / `*_main.py` 的一致命名约定，可读性好
- `_string_id_to_bigint()` 提供确定性 ID 生成，避免自增/随机 ID 的问题
- Supabase client 全局单例 + `reset_client()` 支持测试
- pgvector 嵌入存储与 Supabase 原生集成

**不足：**
- `watchlist_manager.py` 使用本地 JSON 文件存储观察列表，在多实例部署时会导致状态不一致，应迁移到数据库
- 缺少统一的 Repository/DAO 抽象层；每个 `_query.py` 文件都直接操作 Supabase client，代码模式重复
- 存储层的错误处理策略不一致：有的返回空列表，有的抛出异常，有的静默忽略

### 3.3 数据管道设计（Overnight Pipeline）

Overnight Pipeline 是系统的核心，负责将原始新闻聚类为 "故事线"：

```
                          Overnight Pipeline 流程
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  Step 1: Store & Embed Data                                      │
│  ┌────────────────────────────────────────────┐                  │
│  │ run_store_embed_data()                     │                  │
│  │ • 采集所有 ticker 的新闻                     │                  │
│  │ • 生成 Gemini anchor 文章                   │                  │
│  │ • Alpha Vantage / Massive 新闻              │                  │
│  │ • 存储到 news_articles + 生成嵌入向量        │                  │
│  │ • 运行宏观摘要 (可选)                       │                  │
│  │ • 更新 SEC Filing (可选)                    │                  │
│  └────────────────────────────────────────────┘                  │
│                         │                                        │
│                         ▼                                        │
│  Step 2: 获取文章 + 嵌入                                          │
│  ┌────────────────────────────────────────────┐                  │
│  │ • Gemini 文章: created_at 最近 3h           │                  │
│  │ • 其他文章: published_at 最近 18h            │                  │
│  │ • _get_or_embed(): 缺失嵌入的补充生成        │                  │
│  └────────────────────────────────────────────┘                  │
│                         │                                        │
│                         ▼                                        │
│  Step 3: 2-Phase 聚类 (Anchor-Based)                              │
│  ┌────────────────────────────────────────────┐                  │
│  │ run_clustering()                           │                  │
│  │                                            │                  │
│  │  Phase 1 — Seeded Clusters:                │                  │
│  │  • Gemini 文章作为 anchor                   │                  │
│  │  • 非 anchor 文章如果与某 anchor 的          │                  │
│  │    cosine_sim >= T_ASSIGN (0.68) 则归入     │                  │
│  │                                            │                  │
│  │  Phase 2 — Discovered Clusters:            │                  │
│  │  • 未匹配文章之间构建相似度图               │                  │
│  │  • edge if cosine_sim >= T_GRAPH (0.62)    │                  │
│  │  • Union-Find 求连通分量                    │                  │
│  └────────────────────────────────────────────┘                  │
│                         │                                        │
│                         ▼                                        │
│  Step 4: LLM 生成故事 (per cluster)                               │
│  ┌────────────────────────────────────────────┐                  │
│  │ story_llm_call()                           │                  │
│  │ • 将 cluster 内文章送入 gpt-4o-mini         │                  │
│  │ • 生成 title, summary, topics, direction    │                  │
│  │ • 概率性预测 (prob_move, risk_confidence)   │                  │
│  │ • asyncio.gather 并行处理所有 cluster       │                  │
│  └────────────────────────────────────────────┘                  │
│                         │                                        │
│                         ▼                                        │
│  Step 5: 持久化 + Filing Link                                     │
│  ┌────────────────────────────────────────────┐                  │
│  │ • insert_story() → story 表                 │                  │
│  │ • insert_story_article_links()              │                  │
│  │ • 如果 is_filing_related:                   │                  │
│  │   get_most_recent_filing() → top chunk →    │                  │
│  │   insert_story_filing_link()                │                  │
│  └────────────────────────────────────────────┘                  │
│                         │                                        │
│                         ▼                                        │
│  Step 6: Long Story 流程 (可选)                                    │
│  ┌────────────────────────────────────────────┐                  │
│  │ • deserves_long_story_llm() — LLM 判断      │                  │
│  │ • maybe_merge_or_create_long_story()        │                  │
│  │ • 嵌入相似度匹配已有 long story 或新建       │                  │
│  └────────────────────────────────────────────┘                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

**优点：**
- Anchor-based 聚类设计巧妙：利用 Gemini 生成的高质量摘要作为 anchor，确保每个 cluster 有明确主题
- 2-phase 聚类（Seeded + Discovered）兼顾已知主题和新发现主题
- T_ASSIGN / T_GRAPH 阈值可通过环境变量调整，便于调优
- Union-Find 算法用于 discovered cluster 高效且正确
- asyncio.gather 并行处理 LLM 调用，显著提升吞吐量
- Long story 流程支持增量合并，避免重复创建

**不足：**
- Pipeline 代码缺少明确的步骤编排抽象（如 DAG 或 Step Runner），`run_overnight_pipeline()` 是一个 400+ 行的长函数
- 缺少 pipeline 中间状态的持久化和断点恢复能力；如果在 Step 4 失败，需要从 Step 1 重跑
- Discovered clusters 的 O(n²) 相似度矩阵计算在文章量大时可能成为瓶颈
- Story embedding 在 persist_story 中再次生成，与 Step 2 有重复计算

### 3.4 数据库设计

系统使用 Supabase (PostgreSQL + pgvector)，表结构设计如下：

#### 核心表：

| 表名 | 用途 | 关键字段 |
|------|------|---------|
| `news_articles` | 新闻文章存储 | id(bigint), ticker, title, summary, embedding(vector(1536)), published_at, source, collector |
| `story` | 隔夜故事 | id, asof_date, ticker, title, summary, topics, session_label, direction_bias, prob_move_*, risk_* |
| `story_article_link` | 故事-文章关联 | story_id, article_id, role |
| `long_stories` | 长期故事线 | id, ticker, title, canonical_theme, summary, impact_level |
| `long_story_article_links` | 长故事-文章关联 | long_story_id, article_id, relation_type |
| `stocks` | 股票基础信息 | ticker, name, related_tickers |
| `sec_filings` | SEC 文件 | id, ticker, form_type, filed_date, url |
| `sec_filing_chunks` | 文件分块+向量 | id, filing_id, text, embedding |
| `story_filing_link` | 故事-Filing 关联 | story_id, filing_id, top_chunk_id |
| `macro_raw_items` | 宏观原始数据 | 统一存储 8 个 topic 的原始条目 |
| `macro_brief_*` | 宏观分资产简报 | fx, rates, credit, commodity, equity, policy |
| `macro_daily_summary` | 宏观日度汇总 | 合成所有 topic 的每日摘要 |
| `macro_kb_chunks` | 宏观知识库分块 | text, embedding, page_start, page_end |

**优点：**
- pgvector 扩展原生支持向量相似度搜索，与 PostgreSQL 无缝集成
- 确定性 bigint ID（`_string_id_to_bigint`）避免了自增 ID 的分布式冲突和随机 ID 的不可预测性
- 故事-文章通过 link 表关联，支持多对多关系
- 宏观模块按资产类别分表（fx, rates, credit, commodity, equity, policy），查询高效
- 可选 Elasticsearch 混合搜索（BM25 + kNN），提供更好的检索质量

**不足：**
- 缺少数据库 migration 管理工具（如 Alembic），表结构变更依赖手动操作
- 没有看到显式的索引定义（可能在 Supabase 控制面板管理），缺少 code-as-infrastructure
- `_string_id_to_bigint` 使用 MD5 前 7 字节，理论上存在碰撞风险（虽然极低）
- 宏观分资产表（macro_brief_fx, macro_brief_rates...）导致表增长，每新增 topic 需要新建表
- 没有明确的数据保留策略和过期清理机制

### 3.5 前端架构分析

#### 3.5.1 组件层次

```
App.tsx
├── LocaleProvider (i18n)
├── Login
└── Dashboard
    ├── Header (nav + 搜索 + 语言切换)
    ├── Narrative Tab
    │   ├── StockCard[] (卡片列表)
    │   ├── StorylineTable (故事表格)
    │   └── StockDetail
    │       ├── TradingViewChart (K线图)
    │       ├── StorylineTable (该股故事)
    │       ├── LongStoryTimeline
    │       └── NewsFilterPanel
    ├── Macro Tab
    │   └── MacroView
    ├── Ask Tab
    │   └── AskChat
    └── Account Tab (占位)
```

#### 3.5.2 状态管理

前端**没有使用任何状态管理库**（如 Redux, Zustand, Jotai），完全依赖 React `useState` + `useEffect`：

- `Dashboard.tsx` 管理全局状态（portfolio, watchlist, 价格, 故事线数据, tab, selectedStock...）
- 子组件通过 props 接收数据
- `sessionStorage` 用于跨刷新持久化 portfolio/watchlist
- 无全局 store、无 Context（除 i18n）

**优点：**
- 依赖极简（仅 react, react-dom, lightweight-charts, lucide-react, reactflow）
- `api.ts` 集中化 API 访问，避免分散的 fetch 调用
- `useLocale` Hook 提供类型安全的国际化
- 前端时区处理正确：使用 `Intl.DateTimeFormat` 而非固定时区

**不足：**
- `Dashboard.tsx` 是一个 **630+ 行的巨型组件**，包含了几乎所有状态和副作用逻辑，严重违反 SRP
- 没有使用 React Router 进行路由管理，而是手动用 `useState` + URL `?tab=` 参数模拟 tab 切换
- 缺少请求缓存/状态管理（如 SWR, React Query），每次 tab 切换都重新请求
- 部分组件（如 Dashboard）直接使用 `fetch` 而非集中的 `api.ts` 工具函数
- `getOvernightWindowFallback()` 在前端重新实现了后端的 overnight window 计算逻辑，违反 DRY
- 前端类型定义 (`types.ts`) 与后端 Pydantic models (`models.py`) 缺少自动同步机制

### 3.6 可扩展性和模块化评估

#### 3.6.1 新闻源注册机制

新增数据源的步骤清晰：
1. 继承 `BaseCollector` 或 `RSSCollector`
2. 实现 `collect()` 方法
3. 在 `collectors/__init__.py` 导出
4. 在 `config.py` 的 `NEWS_SOURCES` 中添加配置
5. 在 `BriefingGenerator._register_collectors()` 中注册

**评价：** 步骤明确但略微繁琐（5 步手动操作）。可以改进为自动发现注册（如通过装饰器或配置文件自动扫描 collectors 目录）。

#### 3.6.2 Filter Factory 模式

```python
# 根据配置选择过滤策略
filter = FilterFactory.create(filter_type="openai")  # 或 "gemini", "keyword"
# AI 过滤器失败时自动降级为关键词过滤
```

**评价：** 优雅的降级策略，确保系统在 AI 服务不可用时仍能工作。

#### 3.6.3 宏观模块可扩展性

宏观模块设计为 8 个固定 topic，新增 topic 需要：
1. 在 `config.py` 的 `MACRO_TOPICS` 中添加
2. 在 `synthesis.py` 的 `TOPIC_TO_ASSET_KEY` 中添加映射
3. 如果是新的 asset_key，需要新建数据库表 + `_save.py` / `_query.py` 文件

**评价：** 对于预定义的 8 个 topic 工作良好，但扩展到新 topic 需要代码修改 + 数据库表创建，不够灵活。

### 3.7 依赖管理和耦合度分析

#### 3.7.1 耦合度问题

1. **Router → Storage 直接耦合**：`stories.py` 中的大量端点直接调用 `supabase.table(...)` 而不通过 Service 层，绕过了分层抽象
2. **BriefingGenerator 的上帝类问题**：一个类承担了 collector 注册、数据采集、过滤、标签、排序、方向分析、报告生成
3. **Config 模块的全局状态**：`config.py` 通过模块级变量暴露所有配置，任何模块都可以直接引用，缺少命名空间隔离
4. **Pipeline 对具体实现的依赖**：`runner.py` 直接 import 了 10+ 个具体模块，缺少依赖注入

#### 3.7.2 良好的解耦设计

1. **前后端通过 REST API 完全解耦**
2. **Collector 通过 BaseCollector 接口解耦具体实现**
3. **RAG 检索支持 pgvector/Elasticsearch 双后端，通过配置切换**
4. **Embedding 服务通过单例接口隔离 OpenAI 细节**
5. **宏观模块 (`macro/`) 作为独立子系统，有自己的 router、prompts、synthesis 流程**

### 3.8 架构优点总结

1. **清晰的分层架构**：Routers → Services → Storage 的三层结构，各层职责明确
2. **优秀的 Collector 体系**：BaseCollector + Registry + Factory 的组合使数据源管理灵活
3. **创新的聚类设计**：Anchor-based 2-phase clustering 在新闻聚合领域是高效且实用的方案
4. **务实的技术选型**：Supabase + pgvector 兼顾了关系型存储和向量检索，避免了额外的向量数据库运维
5. **优雅的降级策略**：AI filter 降级、Elasticsearch 回退 pgvector、Gemini/OpenAI 互为备选
6. **完善的超时保护**：三层超时（per-collector → aggregator → global）防止系统挂起
7. **国际化支持**：前端原生支持中英文切换
8. **CI/CD 集成**：GitHub Actions 定时运行 pipeline

### 3.9 架构不足和改进建议

#### 高优先级改进

1. **拆分 Dashboard.tsx**（前端最大痛点）
   - 将状态管理抽取到自定义 hooks（如 `usePortfolio()`, `useStorylines()`, `usePrices()`）
   - 引入轻量状态管理（Zustand 或 Jotai）
   - 加入 React Router 做真正的路由管理

2. **拆分 stories.py Router**（后端最大痛点）
   - 将 Ask/Custom Story 独立为 `routers/ask.py`
   - 将 Filing 格式化独立为 `routers/filing.py`
   - 将数据库操作下沉到专门的 `storage/story_query.py`

3. **引入 Pipeline 编排框架**
   - 将 `run_overnight_pipeline()` 拆分为独立的 Step 类
   - 支持断点恢复和中间结果缓存
   - 添加 step-level 的日志和监控指标

#### 中优先级改进

4. **统一 Storage 层抽象**
   - 引入 Repository 基类，消除 `_query.py` 中的重复代码
   - 统一错误处理策略（返回 Optional 还是抛出异常）

5. **前后端类型同步**
   - 使用 OpenAPI spec（FastAPI 自动生成）+ 代码生成器（如 openapi-typescript-codegen）自动生成前端类型

6. **数据库 Migration 管理**
   - 引入 Alembic 或 Supabase Migration 管理表结构变更
   - 将索引定义纳入代码管理

7. **将 Watchlist 迁移到数据库**
   - 替换本地 JSON 文件，支持多实例部署
   - 与用户认证系统关联

#### 低优先级改进

8. **配置模块重构**
   - 将 `config.py`（286 行）按功能域拆分（如 `config/llm.py`, `config/sources.py`, `config/pipeline.py`）
   - 使用 Pydantic Settings 做配置验证

9. **Collector 自动注册**
   - 通过装饰器或目录扫描自动发现和注册 Collector，减少手动步骤

10. **增加集成测试和 E2E 测试**
    - 当前测试主要是单元测试，缺少管道级别的集成测试

### 3.10 架构设计评分

| 维度 | 评分 (1-10) | 说明 |
|------|:-----------:|------|
| 分层清晰度 | 7 | 三层结构清晰，但 Router 层泄漏了过多逻辑 |
| 模块化程度 | 7 | Collector/Filter 体系优秀，但存在几个 God Object |
| 可扩展性 | 8 | 新增数据源容易，宏观 topic 扩展稍受限 |
| 数据库设计 | 7 | pgvector 集成好，缺少 migration 管理和保留策略 |
| 前端架构 | 5 | 功能完整但组件过大、缺少状态管理和路由 |
| 管道设计 | 8 | 聚类算法优秀、并行处理好，缺少编排框架和断点恢复 |
| 耦合度控制 | 6 | 接口抽象好，但存在 Router→DB 直连和 God Class 问题 |
| 降级/容错 | 9 | 多层超时、AI 降级、双 RAG 后端，容错设计出色 |
| 可维护性 | 6 | 命名规范好，但几个核心文件过大，缺少 migration |
| 技术选型 | 8 | FastAPI + Supabase + pgvector + React 选型务实 |

**总体评分：7.1 / 10**

MorningEdge 的架构在 Collector 体系、聚类算法设计和容错机制方面表现出色，技术选型务实高效。主要改进空间在于拆分过大的组件（Dashboard.tsx, stories.py, BriefingGenerator），引入 Pipeline 编排框架，以及完善前端状态管理。对于一个快速迭代的项目，当前架构已经能够很好地支撑业务需求，但随着复杂度增长，上述重构将变得越来越必要。

