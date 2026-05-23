# NL2DSL Web Frontend 设计文档

> **状态：待实现**
>
> 为 NL2DSL 引擎构建配套的前端 Web 应用，提供自然语言查询工作台和管理后台。

---

## 1. 设计目标

| 目标 | 说明 |
|------|------|
| 降低使用门槛 | 业务分析师无需学习 API 或 DSL 语法，自然语言即可查询 |
| 增强结果可信度 | 透明化 AI 执行过程，让用户看清 DSL/SQL/链路，减少不信任感 |
| 提供管理能力 | 管理员可查看审计日志、指标定义、权限配置 |
| 与后端同域部署 | 前端构建产物挂载到 FastAPI 静态文件服务，无需单独部署 |

---

## 2. 技术方案

| 技术 | 版本 | 用途 |
|------|------|------|
| React | 18+ | UI 框架 |
| TypeScript | 5.x | 类型安全 |
| Vite | 5.x | 构建工具 |
| Ant Design | 5.x | 组件库（表格、表单、弹窗） |
| TailwindCSS | 3.x | 布局、间距、响应式 |
| ECharts | 5.x | 数据可视化图表 |
| React Query (TanStack) | 5.x | 服务端状态管理 |
| React Router | 6.x | 前端路由 |

---

## 3. 项目结构

```
web/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── src/
│   ├── main.tsx              # React 入口
│   ├── App.tsx               # 路由 + 布局
│   ├── Layout.tsx            # 侧边栏 + 顶部栏
│   ├── api/
│   │   ├── client.ts         # axios 实例 + 拦截器
│   │   ├── query.ts          # 查询相关 API
│   │   ├── audit.ts          # 审计日志 API
│   │   ├── schema.ts         # Schema API
│   │   └── feedback.ts       # 反馈 API
│   ├── pages/
│   │   ├── QueryPage.tsx     # 查询工作台
│   │   └── AdminPage.tsx     # 管理后台（含子路由）
│   ├── components/
│   │   ├── common/
│   │   │   ├── Loading.tsx
│   │   │   ├── ErrorAlert.tsx
│   │   │   └── JsonViewer.tsx
│   │   ├── query/
│   │   │   ├── QueryInput.tsx
│   │   │   ├── ClarificationDialog.tsx
│   │   │   ├── ResultTable.tsx
│   │   │   ├── ResultChart.tsx
│   │   │   ├── ResultTabs.tsx
│   │   │   ├── TracePanel.tsx
│   │   │   ├── TraceTimeline.tsx
│   │   │   ├── DSLViewer.tsx
│   │   │   ├── SQLPreviewModal.tsx
│   │   │   ├── DSLEditor.tsx
│   │   │   ├── DataSampleCard.tsx
│   │   │   ├── ResultTrustPanel.tsx
│   │   │   ├── QueryHistoryMatch.tsx
│   │   │   ├── FollowUpChips.tsx
│   │   │   ├── FeedbackBar.tsx
│   │   │   └── QueryProgress.tsx
│   │   └── admin/
│   │       ├── MetricTable.tsx
│   │       ├── AuditLogTable.tsx
│   │       ├── AuditTraceDetail.tsx
│   │       └── PermissionTable.tsx
│   ├── types/
│   │   └── api.ts            # 后端 API 类型映射
│   ├── hooks/
│   │   ├── useSSE.ts         # SSE 连接管理
│   │   ├── useQuery.ts       # 查询逻辑封装
│   │   └── useAudit.ts       # 审计日志查询
│   └── styles/
│       └── index.css
└── public/
```

---

## 4. 路由设计

| 路径 | 页面 | 说明 |
|------|------|------|
| `/` | 重定向到 `/query` | 默认进入查询工作台 |
| `/query` | QueryPage | 自然语言查询工作台 |
| `/admin` | AdminPage | 管理后台首页 |
| `/admin/metrics` | MetricTable | 指标管理 |
| `/admin/audit` | AuditLogTable | 审计日志 |
| `/admin/permissions` | PermissionTable | 权限配置 |

---

## 5. 页面设计

### 5.1 查询工作台 (/query)

**布局（单列，居中自适应）：**

```
顶部栏: NL2DSL Query Engine  [dev标签]

┌──────────────────────────────────────────────────────────┐
│ 输入区域                                                  │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ 🔍 查询华东地区销售额...                   [发送]    │ │
│ └──────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────┤
│ 进度区域（SSE 流式时显示）                                │
│ ● 歧义检测 ──○ DSL生成 ──○ 校验 ──○ 权限 ──○ 构建SQL ──○ 执行 │
├──────────────────────────────────────────────────────────┤
│ 结果区域                                                  │
│ [表格] [柱状图] [折线图]                                   │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ product_name │ sales_amount │ region                 │ │
│ │ 产品A        │ 1,234,567    │ 华东                   │ │
│ │ ...          │ ...          │ ...                    │ │
│ └──────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────┤
│ 信任增强面板                                              │
│ 📊 置信度 92%  |  历史上问过 23 次  |  上次结果一致 ✓      │
├──────────────────────────────────────────────────────────┤
│ 详情面板 [DSL] [SQL] [样本数据] [执行链路]                  │
│ ┌──────────────────────────────────────────────────────┐ │
│ │ {                                                    │ │
│ │   "metrics": [...],                                  │ │
│ │   "dimensions": [...]                                │ │
│ │ }                                                    │ │
│ └──────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────┤
│ 追问区域                                                  │
│ [环比上月] [只看华东] [按品牌 breakdown]                     │
├──────────────────────────────────────────────────────────┤
│ 反馈条                                                    │
│ 结果正确吗？  [✅ 正确]  [❌ 数据不对]  [⚠️ 歧义未解决]       │
└──────────────────────────────────────────────────────────┘
```

**核心交互：**

| 交互 | 行为 |
|------|------|
| 输入框 Enter | 发送查询请求 |
| 输入框加载中 | 显示旋转动画，禁用发送按钮 |
| SSE 流式 | 进度条实时更新节点状态 |
| 歧义检测 | 弹出 ClarificationDialog，用户选择后发送确认 |
| 结果切换 | 表格/柱状图/折线图三种视图 |
| SQL 预览 | 点击"查看 SQL"弹窗，展示完整 SQL 语句（可复制） |
| DSL 编辑 | 点击"编辑 DSL"展开编辑器，修改后重新执行 |
| 样本数据 | 展示 3-5 条原始样本记录（带脱敏标记） |
| 反馈提交 | 点击反馈按钮，弹出表单收集详细反馈 |

### 5.2 管理后台 (/admin)

**布局（侧边栏 + 主内容区）：**

```
┌────────┬────────────────────────────────────────────────┐
│ NL2DSL │ 管理后台                                        │
├────────┼────────────────────────────────────────────────┤
│ 📊 指标 │                                                │
│ 📋 审计 │  审计日志                                       │
│ 🔐 权限 │  [今天] [本周] [本月] [全部]                     │
│        │                                                │
│        │  时间      | 用户 | 问题      | 状态 | 耗时    │
│        │  14:23:01 | u001 | 华东销售额 | ✅   | 1.2s   │
│        │  14:20:33 | u001 | 查询销售额 | ⚠️   | 0.3s   │
│        │  14:15:12 | u002 | 全部产品   | ❌   | 2.1s   │
│        │                                                │
│        │  点击行展开详情                                 │
│        │  ┌──────────────────────────────────────────┐  │
│        │  │ Trace:                                   │  │
│        │  │ clarification → dsl_generate → validate  │  │
│        │  │ → permission → build_sql → execute       │  │
│        │  │                                          │  │
│        │  │ DSL: {...}                               │  │
│        │  │ SQL: SELECT ...                          │  │
│        │  │ Error: no such table: order_fact         │  │
│        │  └──────────────────────────────────────────┘  │
└────────┴────────────────────────────────────────────────┘
```

**功能模块：**

| 模块 | 功能 |
|------|------|
| 指标管理 | 只读展示 `configs/metrics.yaml` 内容，表格形式展示指标/维度/数据源 |
| 审计日志 | 列表展示查询历史，支持时间筛选、状态筛选、用户筛选；点击展开 trace 详情 |
| 权限配置 | 只读展示 `configs/permissions.yaml`，展示用户权限映射和敏感列脱敏规则 |

---

## 6. API 集成

### 6.1 查询相关

```typescript
// POST /api/v1/query
interface QueryRequest {
  question: string;
  user_id: string;
  tenant_id: string;
}

interface QueryResponse {
  status: string;
  data: Record<string, unknown>[];
  dsl: DSL;
  sql: string;
  execution_time_ms: number;
}
```

```typescript
// SSE /api/v1/query/stream
interface StreamEvent {
  node: string;           // clarification | dsl | validate | ...
  status: string;         // success | error | pending
  data?: unknown;         // 节点输出数据
  timestamp: number;
}
```

```typescript
// POST /api/v1/query/dsl
interface DSLResponse {
  dsl: DSL;
}
```

### 6.2 审计相关

```typescript
// GET /api/v1/admin/audit/queries?limit=20&offset=0&status=&user_id=
interface AuditListResponse {
  items: AuditItem[];
  total: number;
}

interface AuditItem {
  id: string;
  timestamp: string;
  user_id: string;
  question: string;
  status: 'success' | 'error' | 'clarification' | 'pending_review';
  execution_time_ms: number;
}
```

```typescript
// GET /api/v1/admin/audit/queries/{query_id}
interface AuditDetailResponse {
  id: string;
  question: string;
  dsl: DSL;
  sql: string;
  trace: TraceStep[];
  status: string;
}
```

### 6.3 Schema 相关

```typescript
// GET /api/v1/schema
interface SchemaResponse {
  metrics: Record<string, MetricDef>;
  dimensions: Record<string, DimensionDef>;
  data_sources: Record<string, DataSourceDef>;
}
```

### 6.4 反馈相关

```typescript
// POST /api/v1/feedback
interface FeedbackRequest {
  query_id: string;
  is_correct: boolean;
  issue_type?: 'data_error' | 'ambiguity' | 'performance' | 'other';
  comment?: string;
}
```

---

## 7. 类型定义

```typescript
// types/api.ts

export interface DSL {
  metrics?: Aggregation[];
  dimensions?: string[];
  filters?: Filter[];
  order_by?: OrderBy[];
  limit?: number;
  data_source: string;
  joins?: Join[];
  offset?: number;
  time_field?: string;
  time_range?: TimeRange;
}

export interface Aggregation {
  func: 'sum' | 'avg' | 'count' | 'min' | 'max';
  field: string;
  alias?: string;
}

export interface Filter {
  field: string;
  operator: '=' | '!=' | '>' | '<' | '>=' | '<=' | 'in';
  value: string | number | string[];
}

export interface OrderBy {
  field: string;
  direction: 'asc' | 'desc';
}

export interface Join {
  table: string;
  on_field: string;
  join_type: 'inner' | 'left' | 'right';
  alias?: string;
}

export interface TraceStep {
  step: string;
  status: string;
  duration_ms?: number;
  input?: unknown;
  output?: unknown;
}

export interface ClarificationItem {
  type: string;
  question: string;
  options: string[];
}
```

---

## 8. 状态管理

使用 **React Query** 管理服务端状态，**React Context** 管理全局 UI 状态。

```typescript
// hooks/useQuery.ts
export function useStreamQuery() {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<'idle' | 'streaming' | 'done' | 'error'>('idle');

  const startStream = (req: QueryRequest) => {
    setStatus('streaming');
    setEvents([]);
    const es = new EventSource(`/api/v1/query/stream?body=${encodeURIComponent(JSON.stringify(req))}`, {
      headers: { 'Content-Type': 'application/json' },
    });
    es.onmessage = (e) => {
      const data = JSON.parse(e.data);
      setEvents(prev => [...prev, data]);
      if (data.status === 'end') {
        setStatus('done');
        es.close();
      }
    };
    es.onerror = () => { setStatus('error'); es.close(); };
    return () => es.close();
  };

  return { events, status, startStream };
}
```

---

## 9. 样式与主题

- **主题色**：`#1677ff`（Ant Design 默认蓝）
- **成功色**：`#52c41a`
- **警告色**：`#faad14`
- **错误色**：`#f5222d`
- **背景色**：`#f5f5f5`（页面），`#ffffff`（卡片）
- **布局**：侧边栏固定 200px，主内容区自适应

---

## 10. 部署

### 10.1 前端构建

```bash
cd web/
npm install
npm run build    # 输出 web/dist/
```

### 10.2 后端挂载

```python
# nl2dsl/api.py 添加静态文件服务
from fastapi.staticfiles import StaticFiles

# 在所有 API 路由注册之后、根路由之前
app.mount("/", StaticFiles(directory="web/dist", html=True), name="static")
```

访问 `http://localhost:8000/` 直接打开前端页面。

### 10.3 跨域

前后端同域部署，无需额外跨域配置。若分开部署，后端需配置 CORS：

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 11. 测试策略

| 测试类型 | 工具 | 覆盖内容 |
|----------|------|---------|
| 组件测试 | Vitest + React Testing Library | 各组件独立渲染、事件处理、状态变化 |
| E2E 测试 | Playwright | 完整查询链路：输入 → 发送 → 等待结果 → 验证表格数据 |

---

## 12. 实现优先级

| 优先级 | 模块 | 说明 |
|--------|------|------|
| P0 | 项目骨架 | Vite + React + TS + Ant Design + Tailwind 初始化 |
| P0 | 布局 + 路由 | Layout、Sidebar、Router 配置 |
| P0 | API Client | axios 封装、类型定义 |
| P0 | 查询工作台基础 | QueryInput、ResultTable、基础查询流程 |
| P1 | SSE 流式 | QueryProgress、实时节点状态 |
| P1 | 歧义处理 | ClarificationDialog |
| P1 | 图表 | ResultChart（ECharts 集成） |
| P1 | 信任增强基础 | DSLViewer、SQLPreviewModal、TracePanel |
| P2 | 管理后台 | 指标/审计/权限三个子页面 |
| P2 | 信任增强进阶 | ResultTrustPanel、DataSampleCard、DSLEditor |
| P2 | 反馈 | FeedbackBar、反馈弹窗 |
| P3 | 追问 | FollowUpChips、QueryHistoryMatch |
| P3 | 优化 | 响应式适配、性能优化、无障碍 |

---

## 13. 风险与边界

| 风险 | 缓解措施 |
|------|---------|
| SSE 连接不稳定 | 自动重连 + 超时提示 |
| LLM 响应慢导致前端等待时间长 | 骨架屏 + 节点进度提示 |
| 大数据量表格卡顿 | 虚拟滚动 + 分页 |
| 图表数据类型不匹配 | 自动检测维度/指标类型，选择合适的图表 |
| 构建产物过大 | Vite 代码分割 + 懒加载路由 |

---

## Placeholder Scan

- 无 TBD、TODO
- 所有 API 路径与后端现有接口一致
- 类型定义与后端 Pydantic 模型对齐
- 部署方案明确（同域挂载）
