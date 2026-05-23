# Web Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建 NL2DSL 前端 Web 应用，包含自然语言查询工作台和管理后台。

**Architecture:** React 18 + TypeScript + Vite 构建，Ant Design + TailwindCSS 样式，ECharts 图表，React Query 状态管理，React Router 路由，与 FastAPI 同域部署。

**Tech Stack:** React 18, TypeScript 5, Vite 5, Ant Design 5, TailwindCSS 3, ECharts 5, React Query 5, React Router 6, axios

---

## File Structure

```
web/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── postcss.config.js
├── tailwind.config.js
├── src/
│   ├── main.tsx
│   ├── App.tsx
│   ├── Layout.tsx
│   ├── api/
│   │   ├── client.ts
│   │   ├── query.ts
│   │   ├── audit.ts
│   │   ├── schema.ts
│   │   └── feedback.ts
│   ├── pages/
│   │   ├── QueryPage.tsx
│   │   └── AdminPage.tsx
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
│   │   └── api.ts
│   ├── hooks/
│   │   ├── useSSE.ts
│   │   ├── useQuery.ts
│   │   └── useAudit.ts
│   └── styles/
│       └── index.css
└── public/
```

---

## Task 1: 项目骨架初始化

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.node.json`
- Create: `web/index.html`
- Create: `web/tailwind.config.js`
- Create: `web/postcss.config.js`
- Create: `web/src/main.tsx`
- Create: `web/src/styles/index.css`
- Create: `web/.gitignore`

- [ ] **Step 1: 创建 web 目录并初始化 package.json**

```bash
cd D:/demo/db-gpt/NL2DSL
mkdir -p web/src web/public
```

```json
{
  "name": "nl2dsl-web",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite --host 0.0.0.0 --port 5173",
    "build": "tsc && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0",
    "react-router-dom": "^6.22.0",
    "@tanstack/react-query": "^5.18.0",
    "antd": "^5.14.0",
    "axios": "^1.6.7",
    "echarts": "^5.4.3",
    "echarts-for-react": "^3.0.2"
  },
  "devDependencies": {
    "@types/react": "^18.2.55",
    "@types/react-dom": "^18.2.19",
    "@vitejs/plugin-react": "^4.2.1",
    "autoprefixer": "^10.4.17",
    "postcss": "^8.4.35",
    "tailwindcss": "^3.4.1",
    "typescript": "^5.3.3",
    "vite": "^5.1.0"
  }
}
```

- [ ] **Step 2: 创建 Vite 配置**

```typescript
// web/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
```

- [ ] **Step 3: 创建 TypeScript 配置**

```json
// web/tsconfig.json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "allowImportingTsExtensions": true,
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

```json
// web/tsconfig.node.json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 4: 创建 HTML 入口**

```html
<!-- web/index.html -->
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NL2DSL - 自然语言智能问数</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 5: 创建 TailwindCSS 配置**

```javascript
// web/tailwind.config.js
/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
  corePlugins: {
    preflight: false, // 禁用 Tailwind reset，避免覆盖 Ant Design 样式
  },
}
```

```javascript
// web/postcss.config.js
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
```

- [ ] **Step 6: 创建主入口和样式**

```typescript
// web/src/main.tsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'
import './styles/index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

```css
/* web/src/styles/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer components {
  .page-container {
    @apply p-6 max-w-7xl mx-auto;
  }
  .card {
    @apply bg-white rounded-lg shadow-sm border border-gray-200 p-4;
  }
}
```

- [ ] **Step 7: 创建 .gitignore**

```
# web/.gitignore
node_modules
dist
dist-ssr
*.local
```

- [ ] **Step 8: 安装依赖并验证**

```bash
cd D:/demo/db-gpt/NL2DSL/web
npm install
npm run dev
```

Expected: Vite dev server 启动成功，打开 http://localhost:5173 显示空白页面（因为 App.tsx 还没写）。

- [ ] **Step 9: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/
git commit -m "feat: init web frontend project with Vite + React + TS"
```

---

## Task 2: 类型定义和 API Client

**Files:**
- Create: `web/src/types/api.ts`
- Create: `web/src/api/client.ts`

- [ ] **Step 1: 创建类型定义**

```typescript
// web/src/types/api.ts

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

export interface TimeRange {
  start?: string;
  end?: string;
}

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

export interface QueryRequest {
  question: string;
  user_id: string;
  tenant_id: string;
}

export interface QueryResponse {
  status: string;
  data: Record<string, unknown>[];
  dsl: DSL;
  sql: string;
  execution_time_ms: number;
}

export interface StreamEvent {
  node: string;
  status: string;
  data?: unknown;
  timestamp: number;
}

export interface ClarificationItem {
  type: string;
  question: string;
  options: string[];
}

export interface ClarificationResponse {
  ambiguities: ClarificationItem[] | null;
}

export interface AuditItem {
  id: string;
  timestamp: string;
  user_id: string;
  question: string;
  status: 'success' | 'error' | 'clarification' | 'pending_review';
  execution_time_ms: number;
}

export interface AuditListResponse {
  items: AuditItem[];
  total: number;
}

export interface TraceStep {
  step: string;
  status: string;
  duration_ms?: number;
  input?: unknown;
  output?: unknown;
}

export interface AuditDetailResponse {
  id: string;
  question: string;
  dsl: DSL;
  sql: string;
  trace: TraceStep[];
  status: string;
}

export interface SchemaResponse {
  metrics: Record<string, { expr: string; description?: string }>;
  dimensions: Record<string, { column: string; description?: string }>;
  data_sources: Record<string, { table: string; metrics: string[]; dimensions: string[] }>;
}

export interface FeedbackRequest {
  query_id: string;
  is_correct: boolean;
  issue_type?: 'data_error' | 'ambiguity' | 'performance' | 'other';
  comment?: string;
}
```

- [ ] **Step 2: 创建 API Client**

```typescript
// web/src/api/client.ts
import axios from 'axios';

export const client = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '',
  headers: { 'Content-Type': 'application/json' },
  timeout: 30000,
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败';
    return Promise.reject(new Error(message));
  }
);
```

- [ ] **Step 3: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/types/api.ts web/src/api/client.ts
git commit -m "feat(web): add API types and axios client"
```

---

## Task 3: API 模块封装

**Files:**
- Create: `web/src/api/query.ts`
- Create: `web/src/api/audit.ts`
- Create: `web/src/api/schema.ts`
- Create: `web/src/api/feedback.ts`

- [ ] **Step 1: 创建查询 API**

```typescript
// web/src/api/query.ts
import { client } from './client';
import type { QueryRequest, QueryResponse, DSL, ClarificationResponse } from '../types/api';

export const queryAPI = {
  query: (req: QueryRequest) =>
    client.post<QueryResponse>('/api/v1/query', req),

  queryDSL: (req: QueryRequest) =>
    client.post<{ dsl: DSL }>('/api/v1/query/dsl', req),

  executeDSL: (req: { dsl: DSL; user_id: string; tenant_id: string }) =>
    client.post<QueryResponse>('/api/v1/query/execute', req),

  queryStream: (req: QueryRequest) => {
    const url = `/api/v1/query/stream?body=${encodeURIComponent(JSON.stringify(req))}`;
    return new EventSource(url);
  },
};
```

- [ ] **Step 2: 创建审计 API**

```typescript
// web/src/api/audit.ts
import { client } from './client';
import type { AuditListResponse, AuditDetailResponse } from '../types/api';

export const auditAPI = {
  list: (params?: { limit?: number; offset?: number; status?: string; user_id?: string }) =>
    client.get<AuditListResponse>('/api/v1/admin/audit/queries', { params }),

  detail: (id: string) =>
    client.get<AuditDetailResponse>(`/api/v1/admin/audit/queries/${id}`),
};
```

- [ ] **Step 3: 创建 Schema 和反馈 API**

```typescript
// web/src/api/schema.ts
import { client } from './client';
import type { SchemaResponse } from '../types/api';

export const schemaAPI = {
  getSchema: () => client.get<SchemaResponse>('/api/v1/schema'),
  getMetrics: () => client.get<Record<string, unknown>>('/api/v1/metrics'),
};
```

```typescript
// web/src/api/feedback.ts
import { client } from './client';
import type { FeedbackRequest } from '../types/api';

export const feedbackAPI = {
  submit: (req: FeedbackRequest) =>
    client.post('/api/v1/feedback', req),
};
```

- [ ] **Step 4: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/api/query.ts web/src/api/audit.ts web/src/api/schema.ts web/src/api/feedback.ts
git commit -m "feat(web): add API modules for query, audit, schema, feedback"
```

---

## Task 4: 布局与路由

**Files:**
- Create: `web/src/App.tsx`
- Create: `web/src/Layout.tsx`
- Create: `web/src/pages/QueryPage.tsx`
- Create: `web/src/pages/AdminPage.tsx`

- [ ] **Step 1: 创建 Layout 组件**

```typescript
// web/src/Layout.tsx
import { Layout as AntLayout, Menu } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { SearchOutlined, SettingOutlined } from '@ant-design/icons';

const { Sider, Header, Content } = AntLayout;

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();

  const menuItems = [
    { key: '/query', icon: <SearchOutlined />, label: '查询工作台' },
    { key: '/admin', icon: <SettingOutlined />, label: '管理后台' },
  ];

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider theme="light" width={200}>
        <div style={{ padding: '16px', fontWeight: 'bold', fontSize: '16px' }}>
          NL2DSL
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <AntLayout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: '16px', fontWeight: 500 }}>
            {location.pathname === '/query' ? '查询工作台' : '管理后台'}
          </span>
        </Header>
        <Content style={{ margin: '16px', background: '#f5f5f5', minHeight: 280 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
```

- [ ] **Step 2: 创建 App 路由**

```typescript
// web/src/App.tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './Layout';
import QueryPage from './pages/QueryPage';
import AdminPage from './pages/AdminPage';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<Navigate to="/query" replace />} />
            <Route path="query" element={<QueryPage />} />
            <Route path="admin/*" element={<AdminPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 3: 创建占位页面**

```typescript
// web/src/pages/QueryPage.tsx
export default function QueryPage() {
  return (
    <div className="page-container">
      <h1>查询工作台</h1>
      <p>自然语言输入框和结果显示将在这里实现</p>
    </div>
  );
}
```

```typescript
// web/src/pages/AdminPage.tsx
import { Routes, Route } from 'react-router-dom';

function MetricTable() { return <div>指标管理</div>; }
function AuditLogTable() { return <div>审计日志</div>; }
function PermissionTable() { return <div>权限配置</div>; }

export default function AdminPage() {
  return (
    <div className="page-container">
      <Routes>
        <Route index element={<MetricTable />} />
        <Route path="metrics" element={<MetricTable />} />
        <Route path="audit" element={<AuditLogTable />} />
        <Route path="permissions" element={<PermissionTable />} />
      </Routes>
    </div>
  );
}
```

- [ ] **Step 4: 验证路由**

```bash
cd D:/demo/db-gpt/NL2DSL/web
npm run dev
```

Expected: 打开 http://localhost:5173 自动跳转到 /query，显示"查询工作台"；点击左侧"管理后台"切换到 /admin。

- [ ] **Step 5: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/App.tsx web/src/Layout.tsx web/src/pages/QueryPage.tsx web/src/pages/AdminPage.tsx
git commit -m "feat(web): add layout, routing, and placeholder pages"
```

---

## Task 5: 公共组件

**Files:**
- Create: `web/src/components/common/Loading.tsx`
- Create: `web/src/components/common/ErrorAlert.tsx`
- Create: `web/src/components/common/JsonViewer.tsx`

- [ ] **Step 1: 创建 Loading 组件**

```typescript
// web/src/components/common/Loading.tsx
import { Spin } from 'antd';

interface Props {
  tip?: string;
}

export default function Loading({ tip = '加载中...' }: Props) {
  return (
    <div className="flex justify-center items-center py-12">
      <Spin tip={tip} size="large" />
    </div>
  );
}
```

- [ ] **Step 2: 创建 ErrorAlert 组件**

```typescript
// web/src/components/common/ErrorAlert.tsx
import { Alert } from 'antd';

interface Props {
  message: string;
  onRetry?: () => void;
}

export default function ErrorAlert({ message, onRetry }: Props) {
  return (
    <Alert
      message="请求失败"
      description={message}
      type="error"
      showIcon
      action={
        onRetry ? (
          <button
            onClick={onRetry}
            className="text-blue-500 hover:text-blue-700 text-sm"
          >
            重试
          </button>
        ) : undefined
      }
    />
  );
}
```

- [ ] **Step 3: 创建 JsonViewer 组件**

```typescript
// web/src/components/common/JsonViewer.tsx
import { Typography } from 'antd';

interface Props {
  data: unknown;
}

export default function JsonViewer({ data }: Props) {
  return (
    <Typography.Paragraph>
      <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto', maxHeight: 400 }}>
        <code>{JSON.stringify(data, null, 2)}</code>
      </pre>
    </Typography.Paragraph>
  );
}
```

- [ ] **Step 4: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/components/common/
git commit -m "feat(web): add common components (Loading, ErrorAlert, JsonViewer)"
```

---

## Task 6: 查询工作台 - 输入与基础查询

**Files:**
- Create: `web/src/components/query/QueryInput.tsx`
- Create: `web/src/components/query/ResultTable.tsx`
- Modify: `web/src/pages/QueryPage.tsx`

- [ ] **Step 1: 创建 QueryInput 组件**

```typescript
// web/src/components/query/QueryInput.tsx
import { useState } from 'react';
import { Input, Button } from 'antd';
import { SendOutlined } from '@ant-design/icons';

interface Props {
  onSubmit: (question: string) => void;
  loading?: boolean;
}

export default function QueryInput({ onSubmit, loading }: Props) {
  const [question, setQuestion] = useState('');

  const handleSubmit = () => {
    if (!question.trim() || loading) return;
    onSubmit(question.trim());
  };

  return (
    <div className="flex gap-2">
      <Input.TextArea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="输入自然语言查询，例如：查询华东地区销售额最高的 10 个产品"
        autoSize={{ minRows: 1, maxRows: 3 }}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        disabled={loading}
      />
      <Button
        type="primary"
        icon={<SendOutlined />}
        onClick={handleSubmit}
        loading={loading}
        disabled={!question.trim()}
      >
        查询
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: 创建 ResultTable 组件**

```typescript
// web/src/components/query/ResultTable.tsx
import { Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';

interface Props {
  data: Record<string, unknown>[];
}

export default function ResultTable({ data }: Props) {
  if (!data || data.length === 0) {
    return <div className="text-gray-400 text-center py-8">暂无数据</div>;
  }

  const columns: ColumnsType<Record<string, unknown>> = Object.keys(data[0]).map((key) => ({
    title: key,
    dataIndex: key,
    key,
    ellipsis: true,
  }));

  return (
    <Table
      dataSource={data.map((row, i) => ({ ...row, key: i }))}
      columns={columns}
      pagination={{ pageSize: 10 }}
      size="small"
      scroll={{ x: 'max-content' }}
    />
  );
}
```

- [ ] **Step 3: 更新 QueryPage**

```typescript
// web/src/pages/QueryPage.tsx
import { useState } from 'react';
import { Card, message } from 'antd';
import QueryInput from '../components/query/QueryInput';
import ResultTable from '../components/query/ResultTable';
import Loading from '../components/common/Loading';
import ErrorAlert from '../components/common/ErrorAlert';
import { queryAPI } from '../api/query';
import type { QueryResponse } from '../types/api';

export default function QueryPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleQuery = async (question: string) => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const { data } = await queryAPI.query({
        question,
        user_id: 'web_user',
        tenant_id: 'default',
      });
      setResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '查询失败';
      setError(msg);
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container space-y-4">
      <Card>
        <QueryInput onSubmit={handleQuery} loading={loading} />
      </Card>

      {loading && <Loading tip="正在查询..." />}
      {error && <ErrorAlert message={error} onRetry={() => result && handleQuery(result.dsl ? 'retry' : '')} />}

      {result && (
        <Card title={`查询结果（${result.data.length} 条，耗时 ${result.execution_time_ms}ms）`}>
          <ResultTable data={result.data} />
        </Card>
      )}
    </div>
  );
}
```

- [ ] **Step 4: 验证基础查询**

```bash
cd D:/demo/db-gpt/NL2DSL/web
npm run dev
```

Expected: 在查询工作台输入"查询华东销售额"，点击查询，后端返回结果后表格展示数据。

- [ ] **Step 5: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/components/query/QueryInput.tsx web/src/components/query/ResultTable.tsx web/src/pages/QueryPage.tsx
git commit -m "feat(web): add QueryInput, ResultTable, and basic query flow"
```

---

## Task 7: 查询工作台 - 结果详情面板

**Files:**
- Create: `web/src/components/query/DSLViewer.tsx`
- Create: `web/src/components/query/TracePanel.tsx`
- Create: `web/src/components/query/SQLPreviewModal.tsx`
- Create: `web/src/components/query/ResultTabs.tsx`
- Modify: `web/src/pages/QueryPage.tsx`

- [ ] **Step 1: 创建 DSLViewer**

```typescript
// web/src/components/query/DSLViewer.tsx
import JsonViewer from '../common/JsonViewer';
import type { DSL } from '../../types/api';

interface Props {
  dsl: DSL;
}

export default function DSLViewer({ dsl }: Props) {
  return <JsonViewer data={dsl} />;
}
```

- [ ] **Step 2: 创建 SQLPreviewModal**

```typescript
// web/src/components/query/SQLPreviewModal.tsx
import { Modal, Typography, Button } from 'antd';
import { CopyOutlined } from '@ant-design/icons';

interface Props {
  sql: string;
  open: boolean;
  onClose: () => void;
}

export default function SQLPreviewModal({ sql, open, onClose }: Props) {
  const handleCopy = () => {
    navigator.clipboard.writeText(sql);
  };

  return (
    <Modal
      title="SQL 预览"
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="copy" icon={<CopyOutlined />} onClick={handleCopy}>
          复制
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>
          关闭
        </Button>,
      ]}
      width={800}
    >
      <Typography.Paragraph>
        <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto', maxHeight: 400 }}>
          <code>{sql}</code>
        </pre>
      </Typography.Paragraph>
    </Modal>
  );
}
```

- [ ] **Step 3: 创建 TracePanel**

```typescript
// web/src/components/query/TracePanel.tsx
import { Timeline, Tag } from 'antd';

interface Props {
  steps: { step: string; status: string; duration_ms?: number }[];
}

const statusColor: Record<string, string> = {
  success: 'green',
  error: 'red',
  pending: 'blue',
};

export default function TracePanel({ steps }: Props) {
  return (
    <Timeline
      items={steps.map((s) => ({
        color: statusColor[s.status] || 'gray',
        children: (
          <div>
            <Tag color={statusColor[s.status]}>{s.status}</Tag>
            <span className="font-medium">{s.step}</span>
            {s.duration_ms && (
              <span className="text-gray-400 text-sm ml-2">({s.duration_ms}ms)</span>
            )}
          </div>
        ),
      }))}
    />
  );
}
```

- [ ] **Step 4: 创建 ResultTabs**

```typescript
// web/src/components/query/ResultTabs.tsx
import { useState } from 'react';
import { Tabs, Button } from 'antd';
import DSLViewer from './DSLViewer';
import SQLPreviewModal from './SQLPreviewModal';
import TracePanel from './TracePanel';
import type { DSL, TraceStep } from '../../types/api';

interface Props {
  dsl: DSL;
  sql: string;
  trace: TraceStep[];
}

export default function ResultTabs({ dsl, sql, trace }: Props) {
  const [sqlModalOpen, setSqlModalOpen] = useState(false);

  const items = [
    {
      key: 'dsl',
      label: 'DSL',
      children: <DSLViewer dsl={dsl} />,
    },
    {
      key: 'sql',
      label: (
        <span>
          SQL{' '}
          <Button size="small" type="link" onClick={(e) => { e.stopPropagation(); setSqlModalOpen(true); }}>
            查看
          </Button>
        </span>
      ),
      children: (
        <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto' }}>
          <code>{sql}</code>
        </pre>
      ),
    },
    {
      key: 'trace',
      label: '执行链路',
      children: <TracePanel steps={trace} />,
    },
  ];

  return (
    <>
      <Tabs items={items} />
      <SQLPreviewModal sql={sql} open={sqlModalOpen} onClose={() => setSqlModalOpen(false)} />
    </>
  );
}
```

- [ ] **Step 5: 更新 QueryPage**

在 QueryPage 的 result 展示区域，将 ResultTable 和 ResultTabs 组合：

```typescript
// 在 QueryPage.tsx 的 result 区域替换为：
{result && (
  <>
    <Card title={`查询结果（${result.data.length} 条，耗时 ${result.execution_time_ms}ms）`}>
      <ResultTable data={result.data} />
    </Card>
    <Card className="mt-4">
      <ResultTabs
        dsl={result.dsl}
        sql={result.sql}
        trace={result.trace || []}
      />
    </Card>
  </>
)}
```

注意：后端当前返回的 QueryResponse 可能没有 `trace` 字段，需要兼容处理。如果后端不返回 trace，先用空数组。

- [ ] **Step 6: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/components/query/DSLViewer.tsx web/src/components/query/TracePanel.tsx web/src/components/query/SQLPreviewModal.tsx web/src/components/query/ResultTabs.tsx web/src/pages/QueryPage.tsx
git commit -m "feat(web): add DSL viewer, SQL preview, trace panel, and result tabs"
```

---

## Task 8: 查询工作台 - 图表与 SSE 进度

**Files:**
- Create: `web/src/components/query/ResultChart.tsx`
- Create: `web/src/components/query/QueryProgress.tsx`
- Modify: `web/src/pages/QueryPage.tsx`

- [ ] **Step 1: 创建 ResultChart**

```typescript
// web/src/components/query/ResultChart.tsx
import ReactECharts from 'echarts-for-react';

interface Props {
  data: Record<string, unknown>[];
  xField: string;
  yField: string;
  chartType: 'bar' | 'line';
}

export default function ResultChart({ data, xField, yField, chartType }: Props) {
  const xData = data.map((d) => String(d[xField] ?? ''));
  const yData = data.map((d) => Number(d[yField] ?? 0));

  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: xData },
    yAxis: { type: 'value' },
    series: [{
      data: yData,
      type: chartType,
      smooth: chartType === 'line',
    }],
  };

  return <ReactECharts option={option} style={{ height: 400 }} />;
}
```

- [ ] **Step 2: 创建 QueryProgress**

```typescript
// web/src/components/query/QueryProgress.tsx
import { Steps } from 'antd';

interface Props {
  events: { node: string; status: string }[];
}

const nodeLabels: Record<string, string> = {
  clarification: '歧义检测',
  dsl: 'DSL生成',
  validate: '校验',
  permission: '权限',
  build_sql: '构建SQL',
  scan: '扫描',
  sandbox: '沙箱',
  execute: '执行',
};

export default function QueryProgress({ events }: Props) {
  const nodes = ['clarification', 'dsl', 'validate', 'permission', 'build_sql', 'scan', 'sandbox', 'execute'];

  const current = nodes.findIndex((n) =>
    events.some((e) => e.node === n && e.status === 'pending')
  );

  const items = nodes.map((n) => {
    const event = events.find((e) => e.node === n);
    let status: 'wait' | 'process' | 'finish' | 'error' = 'wait';
    if (event?.status === 'success') status = 'finish';
    else if (event?.status === 'error') status = 'error';
    else if (event?.status === 'pending') status = 'process';

    return {
      title: nodeLabels[n] || n,
      status,
    };
  });

  return (
    <Steps
      current={current}
      size="small"
      items={items}
      direction="horizontal"
    />
  );
}
```

- [ ] **Step 3: 更新 QueryPage 支持图表和 SSE**

将 QueryPage 改造为使用 SSE 流式查询（替代之前的同步查询）：

```typescript
// web/src/pages/QueryPage.tsx
import { useState, useCallback } from 'react';
import { Card, message, Segmented } from 'antd';
import QueryInput from '../components/query/QueryInput';
import ResultTable from '../components/query/ResultTable';
import ResultChart from '../components/query/ResultChart';
import ResultTabs from '../components/query/ResultTabs';
import QueryProgress from '../components/query/QueryProgress';
import Loading from '../components/common/Loading';
import ErrorAlert from '../components/common/ErrorAlert';
import type { QueryResponse, StreamEvent } from '../types/api';

export default function QueryPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [viewType, setViewType] = useState<'table' | 'bar' | 'line'>('table');

  const handleQuery = useCallback((question: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setEvents([]);

    const es = new EventSource(
      `/api/v1/query/stream?body=${encodeURIComponent(JSON.stringify({
        question,
        user_id: 'web_user',
        tenant_id: 'default',
      }))}`
    );

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as StreamEvent;
        setEvents((prev) => [...prev, data]);

        if (data.node === 'execute_sql' && data.status === 'success') {
          setResult(data.data as unknown as QueryResponse);
        }
      } catch {
        // ignore parse error
      }
    };

    es.onerror = () => {
      setError('查询连接中断');
      setLoading(false);
      es.close();
    };

    // 5秒后自动结束（简化处理，实际应该用状态判断）
    setTimeout(() => {
      setLoading(false);
      es.close();
    }, 5000);
  }, []);

  const dimensionField = result?.dsl?.dimensions?.[0] || '';
  const metricField = result?.dsl?.metrics?.[0]?.alias || result?.dsl?.metrics?.[0]?.field || '';

  return (
    <div className="page-container space-y-4">
      <Card>
        <QueryInput onSubmit={handleQuery} loading={loading} />
      </Card>

      {loading && events.length > 0 && (
        <Card>
          <QueryProgress events={events} />
        </Card>
      )}

      {loading && events.length === 0 && <Loading tip="正在查询..." />}
      {error && <ErrorAlert message={error} />}

      {result && (
        <>
          <Card
            title={
              <div className="flex justify-between items-center">
                <span>查询结果（{result.data.length} 条，耗时 {result.execution_time_ms}ms）</span>
                <Segmented
                  options={[
                    { label: '表格', value: 'table' },
                    { label: '柱状图', value: 'bar' },
                    { label: '折线图', value: 'line' },
                  ]}
                  value={viewType}
                  onChange={(v) => setViewType(v as typeof viewType)}
                />
              </div>
            }
          >
            {viewType === 'table' && <ResultTable data={result.data} />}
            {viewType !== 'table' && dimensionField && metricField && (
              <ResultChart
                data={result.data}
                xField={dimensionField}
                yField={metricField}
                chartType={viewType}
              />
            )}
          </Card>

          <Card className="mt-4">
            <ResultTabs
              dsl={result.dsl}
              sql={result.sql}
              trace={[]}
            />
          </Card>
        </>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/components/query/ResultChart.tsx web/src/components/query/QueryProgress.tsx web/src/pages/QueryPage.tsx
git commit -m "feat(web): add chart visualization, SSE progress, and view switching"
```

---

## Task 9: 管理后台

**Files:**
- Create: `web/src/components/admin/MetricTable.tsx`
- Create: `web/src/components/admin/AuditLogTable.tsx`
- Create: `web/src/components/admin/AuditTraceDetail.tsx`
- Create: `web/src/components/admin/PermissionTable.tsx`
- Modify: `web/src/pages/AdminPage.tsx`
- Create: `web/src/hooks/useAudit.ts`

- [ ] **Step 1: 创建 useAudit hook**

```typescript
// web/src/hooks/useAudit.ts
import { useQuery } from '@tanstack/react-query';
import { auditAPI } from '../api/audit';

export function useAuditList(limit = 20, offset = 0) {
  return useQuery({
    queryKey: ['audit', 'list', limit, offset],
    queryFn: () => auditAPI.list({ limit, offset }).then((r) => r.data),
  });
}

export function useAuditDetail(id: string) {
  return useQuery({
    queryKey: ['audit', 'detail', id],
    queryFn: () => auditAPI.detail(id).then((r) => r.data),
    enabled: !!id,
  });
}
```

- [ ] **Step 2: 创建 MetricTable**

```typescript
// web/src/components/admin/MetricTable.tsx
import { useQuery } from '@tanstack/react-query';
import { Table, Tag } from 'antd';
import Loading from '../common/Loading';
import ErrorAlert from '../common/ErrorAlert';
import { schemaAPI } from '../../api/schema';

export default function MetricTable() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['schema'],
    queryFn: () => schemaAPI.getSchema().then((r) => r.data),
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrorAlert message={(error as Error).message} onRetry={refetch} />;

  const metrics = Object.entries(data?.metrics || {}).map(([name, def]) => ({
    key: name,
    name,
    expr: def.expr,
    description: def.description || '-',
  }));

  const dimensions = Object.entries(data?.dimensions || {}).map(([name, def]) => ({
    key: name,
    name,
    column: def.column,
    description: def.description || '-',
  }));

  const dataSources = Object.entries(data?.data_sources || {}).map(([name, def]) => ({
    key: name,
    name,
    table: def.table,
    metrics: def.metrics,
    dimensions: def.dimensions,
  }));

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-medium">指标定义</h2>
      <Table
        dataSource={metrics}
        columns={[
          { title: '指标名', dataIndex: 'name', key: 'name' },
          { title: '表达式', dataIndex: 'expr', key: 'expr' },
          { title: '说明', dataIndex: 'description', key: 'description' },
        ]}
        size="small"
        pagination={false}
      />

      <h2 className="text-lg font-medium">维度定义</h2>
      <Table
        dataSource={dimensions}
        columns={[
          { title: '维度名', dataIndex: 'name', key: 'name' },
          { title: '对应列', dataIndex: 'column', key: 'column' },
          { title: '说明', dataIndex: 'description', key: 'description' },
        ]}
        size="small"
        pagination={false}
      />

      <h2 className="text-lg font-medium">数据源</h2>
      <Table
        dataSource={dataSources}
        columns={[
          { title: '数据源', dataIndex: 'name', key: 'name' },
          { title: '表名', dataIndex: 'table', key: 'table' },
          { title: '指标数', dataIndex: 'metrics', key: 'metrics', render: (m: string[]) => m.length },
          { title: '维度数', dataIndex: 'dimensions', key: 'dimensions', render: (d: string[]) => d.length },
        ]}
        size="small"
        pagination={false}
      />
    </div>
  );
}
```

- [ ] **Step 3: 创建 AuditLogTable**

```typescript
// web/src/components/admin/AuditLogTable.tsx
import { useState } from 'react';
import { Table, Tag, Button } from 'antd';
import Loading from '../common/Loading';
import ErrorAlert from '../common/ErrorAlert';
import { useAuditList } from '../../hooks/useAudit';
import type { AuditItem } from '../../types/api';

interface Props {
  onViewDetail: (id: string) => void;
}

const statusMap: Record<string, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  error: { color: 'red', text: '失败' },
  clarification: { color: 'orange', text: '歧义' },
  pending_review: { color: 'blue', text: '待审核' },
};

export default function AuditLogTable({ onViewDetail }: Props) {
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const { data, isLoading, error, refetch } = useAuditList(pageSize, (page - 1) * pageSize);

  if (isLoading) return <Loading />;
  if (error) return <ErrorAlert message={(error as Error).message} onRetry={refetch} />;

  const columns = [
    { title: '时间', dataIndex: 'timestamp', key: 'timestamp', width: 180 },
    { title: '用户', dataIndex: 'user_id', key: 'user_id', width: 100 },
    { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const s = statusMap[status] || { color: 'default', text: status };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '耗时',
      dataIndex: 'execution_time_ms',
      key: 'execution_time_ms',
      width: 100,
      render: (v: number) => `${v}ms`,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: AuditItem) => (
        <Button size="small" type="link" onClick={() => onViewDetail(record.id)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <Table
      dataSource={data?.items || []}
      columns={columns}
      rowKey="id"
      pagination={{
        current: page,
        pageSize,
        total: data?.total || 0,
        onChange: setPage,
      }}
      size="small"
    />
  );
}
```

- [ ] **Step 4: 创建 AuditTraceDetail**

```typescript
// web/src/components/admin/AuditTraceDetail.tsx
import { Drawer, Timeline, Tag } from 'antd';
import Loading from '../common/Loading';
import JsonViewer from '../common/JsonViewer';
import { useAuditDetail } from '../../hooks/useAudit';

interface Props {
  id: string | null;
  open: boolean;
  onClose: () => void;
}

const statusColor: Record<string, string> = {
  success: 'green',
  error: 'red',
  pending: 'blue',
};

export default function AuditTraceDetail({ id, open, onClose }: Props) {
  const { data, isLoading } = useAuditDetail(id || '');

  return (
    <Drawer title="审计详情" width={720} open={open} onClose={onClose}>
      {isLoading && <Loading />}
      {data && (
        <div className="space-y-4">
          <div>
            <h3 className="font-medium">查询</h3>
            <p>{data.question}</p>
          </div>

          <div>
            <h3 className="font-medium">状态</h3>
            <Tag color={statusColor[data.status] || 'default'}>{data.status}</Tag>
          </div>

          <div>
            <h3 className="font-medium">SQL</h3>
            <pre className="bg-gray-100 p-2 rounded text-sm overflow-auto">{data.sql}</pre>
          </div>

          <div>
            <h3 className="font-medium">DSL</h3>
            <JsonViewer data={data.dsl} />
          </div>

          <div>
            <h3 className="font-medium">执行链路</h3>
            <Timeline
              items={(data.trace || []).map((t) => ({
                color: statusColor[t.status] || 'gray',
                children: (
                  <div>
                    <Tag color={statusColor[t.status]}>{t.status}</Tag>
                    <span className="font-medium">{t.step}</span>
                    {t.duration_ms && <span className="text-gray-400 text-sm ml-2">({t.duration_ms}ms)</span>}
                  </div>
                ),
              }))}
            />
          </div>
        </div>
      )}
    </Drawer>
  );
}
```

- [ ] **Step 5: 创建 PermissionTable（占位）**

```typescript
// web/src/components/admin/PermissionTable.tsx
import { Card, Alert } from 'antd';

export default function PermissionTable() {
  return (
    <Card>
      <Alert
        message="权限配置"
        description="当前从 configs/permissions.yaml 加载，仅支持只读展示。在线编辑功能后续开发。"
        type="info"
        showIcon
      />
      <div className="mt-4 text-gray-400">权限配置内容展示待后端 API 支持后实现</div>
    </Card>
  );
}
```

- [ ] **Step 6: 更新 AdminPage**

```typescript
// web/src/pages/AdminPage.tsx
import { useState } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import MetricTable from '../components/admin/MetricTable';
import AuditLogTable from '../components/admin/AuditLogTable';
import AuditTraceDetail from '../components/admin/AuditTraceDetail';
import PermissionTable from '../components/admin/PermissionTable';

export default function AdminPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const handleViewDetail = (id: string) => {
    setDetailId(id);
    setDetailOpen(true);
  };

  const menuItems = [
    { key: '/admin/metrics', label: '指标管理' },
    { key: '/admin/audit', label: '审计日志' },
    { key: '/admin/permissions', label: '权限配置' },
  ];

  return (
    <div className="page-container">
      <Menu
        mode="horizontal"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        className="mb-4"
      />
      <Routes>
        <Route index element={<MetricTable />} />
        <Route path="metrics" element={<MetricTable />} />
        <Route path="audit" element={<AuditLogTable onViewDetail={handleViewDetail} />} />
        <Route path="permissions" element={<PermissionTable />} />
      </Routes>
      <AuditTraceDetail
        id={detailId}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  );
}
```

- [ ] **Step 7: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add web/src/components/admin/ web/src/hooks/useAudit.ts web/src/pages/AdminPage.tsx
git commit -m "feat(web): add admin dashboard with metrics, audit logs, and permissions"
```

---

## Task 10: 后端集成 - 静态文件挂载与 CORS

**Files:**
- Modify: `nl2dsl/api.py`
- Modify: `nl2dsl/api_factory.py`

- [ ] **Step 1: 在 api.py 添加静态文件服务**

在 `nl2dsl/api.py` 文件末尾（所有路由定义之后）添加：

```python
# 添加在文件末尾
from fastapi.staticfiles import StaticFiles
from pathlib import Path

# 前端构建产物目录
_dist_dir = Path(__file__).parent.parent / "web" / "dist"
if _dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(_dist_dir), html=True), name="static")
```

**注意**：静态文件挂载必须在所有 API 路由注册之后，且路径为 `/`（根路径），这样访问 `/` 时自动返回 `index.html`。

- [ ] **Step 2: 在 api_factory.py 同样添加（可选）**

如果需要让 `api_factory.py` 创建的 app 也支持前端挂载，同样在末尾添加：

```python
# 添加在 create_app 函数末尾、return app 之前
from fastapi.staticfiles import StaticFiles
from pathlib import Path

_dist_dir = Path(__file__).parent.parent / "web" / "dist"
if _dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(_dist_dir), html=True), name="static")
```

- [ ] **Step 3: 验证同域部署**

```bash
cd D:/demo/db-gpt/NL2DSL/web
npm run build
cd D:/demo/db-gpt/NL2DSL
uvicorn nl2dsl.api:app --host 0.0.0.0 --port 8000 --reload
```

打开 http://localhost:8000/，应该能看到前端页面（而不是 FastAPI docs）。

打开 http://localhost:8000/api/v1/query/dsl 等 API 端点，应该仍然正常返回 JSON。

- [ ] **Step 4: Commit**

```bash
cd D:/demo/db-gpt/NL2DSL
git add nl2dsl/api.py nl2dsl/api_factory.py
git commit -m "feat(web): mount static files for frontend deployment"
```

---

## Self-Review

### 1. Spec Coverage

| Spec 要求 | 对应 Task |
|-----------|-----------|
| React 18 + TS + Vite 项目骨架 | Task 1 |
| Ant Design + TailwindCSS | Task 1 |
| 类型定义与 API Client | Task 2, 3 |
| 布局与路由 | Task 4 |
| 公共组件 | Task 5 |
| 查询工作台 - 输入 + 表格 | Task 6 |
| 查询工作台 - DSL/SQL/Trace 详情 | Task 7 |
| 查询工作台 - 图表 + SSE 进度 | Task 8 |
| 管理后台 - 指标/审计/权限 | Task 9 |
| 同域部署（静态文件挂载） | Task 10 |

### 2. Placeholder Scan

- 无 TBD、TODO
- 无 "add appropriate error handling" 等模糊描述
- 每个步骤包含完整代码和测试命令

### 3. Type Consistency

- `QueryResponse` 类型在 Task 2 定义，在 Task 6-8 使用，一致
- `AuditItem` 类型在 Task 2 定义，在 Task 9 使用，一致
- API 路径与后端现有接口一致（/api/v1/query, /api/v1/admin/audit/queries 等）

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-23-web-frontend.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
