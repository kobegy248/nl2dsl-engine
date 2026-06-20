/**
 * 第三轮审阅 P1：Web 审计 tenant_id 契约单元测试。
 *
 * 后端强制审计 list/detail 必须传非空 tenant_id，否则 400。这些测试
 * 验证前端 API 客户端与 useAudit hook 全链路携带 tenant_id，且租户未
 * 就绪时不发请求、切换租户不复用其他租户缓存。
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';

// 启用 React act() 支持，消除 vitest/jsdom 下的 act 警告。
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// --- 可控租户上下文：替代真实 TenantContext，便于在测试中切换租户 -----
const tenantState: { tenantId: string; ready: boolean } = {
  tenantId: 't001',
  ready: true,
};
vi.mock('../context/TenantContext', () => ({
  useTenant: () => tenantState,
}));

// --- 捕获 client.get 的请求 URL 与 params，并返回最小合法响应 -------
const getMock = vi.fn();
vi.mock('../api/client', () => ({
  client: { get: (...args: unknown[]) => getMock(...args) },
}));

// 在 mock 建立后再引入被测模块，确保它们使用 mock 后的依赖。
import { auditAPI } from '../api/audit';
import { useAuditList, useAuditDetail } from './useAudit';

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

interface HarnessApi<T> {
  result: { current: T };
  rerender: () => void;
  unmount: () => void;
}

/**
 * 极简 renderHook：用真实 QueryClient + TenantProvider(mock) 渲染，
 * 通过 Probe 组件把 hook 返回值写到外部 result.current。
 */
function renderHook<T>(hookFn: () => T): HarnessApi<T> {
  const result: { current: T } = { current: undefined as unknown as T };
  function Probe() {
    result.current = hookFn();
    return null;
  }
  const container = document.createElement('div');
  document.body.appendChild(container);
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  });
  let root: Root = createRoot(container);
  act(() => {
    root.render(
      <QueryClientProvider client={qc}>
        <Probe />
      </QueryClientProvider>,
    );
  });
  return {
    result,
    rerender: () => {
      act(() => {
        root.render(
          <QueryClientProvider client={qc}>
            <Probe />
          </QueryClientProvider>,
        );
      });
    },
    unmount: () => {
      act(() => {
        root.unmount();
      });
      container.remove();
    },
  };
}

beforeEach(() => {
  getMock.mockReset();
  getMock.mockImplementation((url: string) => {
    if (url.includes('/queries/')) {
      // detail
      return Promise.resolve({ data: { item: { query_id: 'q1' } } });
    }
    return Promise.resolve({ data: { items: [], total: 0 } });
  });
  tenantState.tenantId = 't001';
  tenantState.ready = true;
});

afterEach(() => {
  vi.useRealTimers();
});

describe('auditAPI — tenant_id 必须随请求下发', () => {
  it('list 请求参数包含 tenant_id', async () => {
    await auditAPI.list({ tenant_id: 't001', limit: 20 });
    expect(getMock).toHaveBeenCalledTimes(1);
    const [, config] = getMock.mock.calls[0];
    expect(config.params.tenant_id).toBe('t001');
  });

  it('detail 请求参数包含 tenant_id', async () => {
    await auditAPI.detail('q1', 't001');
    expect(getMock).toHaveBeenCalledTimes(1);
    const [url, config] = getMock.mock.calls[0];
    expect(url).toContain('/queries/q1');
    expect(config.params.tenant_id).toBe('t001');
  });

  it('未传 tenant_id 时类型层即拒绝（参数必填）', () => {
    // AuditListParams 将 tenant_id 声明为必填；此处仅校验运行期调用仍需显式提供。
    // @ts-expect-error — 缺少必填 tenant_id
    const fn = () => auditAPI.list({ limit: 20 });
    expect(fn).not.toThrow();
  });
});

describe('useAuditList — queryKey 与租户隔离', () => {
  it('hook 触发的请求携带 tenant_id（不再因缺参 400）', async () => {
    const h = renderHook(() => useAuditList(20, 0));
    await act(async () => { await flushPromises(); });
    expect(getMock).toHaveBeenCalledTimes(1);
    const [, config] = getMock.mock.calls[0];
    expect(config.params.tenant_id).toBe('t001');
    h.unmount();
  });

  it('tenant_id 未就绪时查询 disabled，不发请求', async () => {
    tenantState.tenantId = '';
    tenantState.ready = false;
    const h = renderHook(() => useAuditList(20, 0));
    await act(async () => { await flushPromises(); });
    expect(getMock).not.toHaveBeenCalled();
    h.unmount();
  });

  it('切换 tenant_id 后发起新请求，不复用其他租户缓存', async () => {
    const h = renderHook(() => useAuditList(20, 0));
    await act(async () => { await flushPromises(); });
    expect(getMock).toHaveBeenCalledTimes(1);
    expect(getMock.mock.calls[0][1].params.tenant_id).toBe('t001');

    // 切换租户并重渲染：queryKey 变化 → 触发新请求。
    tenantState.tenantId = 't002';
    h.rerender();
    await act(async () => { await flushPromises(); });

    const lastCall = getMock.mock.calls[getMock.mock.calls.length - 1];
    expect(lastCall[1].params.tenant_id).toBe('t002');
    // 至少两次请求，证明没有把 t001 的缓存当作 t002 的结果。
    expect(getMock.mock.calls.length).toBeGreaterThanOrEqual(2);
    h.unmount();
  });
});

describe('useAuditDetail — tenant_id 随详情请求下发', () => {
  it('detail hook 请求携带 tenant_id', async () => {
    const h = renderHook(() => useAuditDetail('q1'));
    await act(async () => { await flushPromises(); });
    expect(getMock).toHaveBeenCalledTimes(1);
    const [, config] = getMock.mock.calls[0];
    expect(config.params.tenant_id).toBe('t001');
    h.unmount();
  });

  it('tenant_id 未就绪时 detail 查询 disabled', async () => {
    tenantState.tenantId = '';
    tenantState.ready = false;
    const h = renderHook(() => useAuditDetail('q1'));
    await act(async () => { await flushPromises(); });
    expect(getMock).not.toHaveBeenCalled();
    h.unmount();
  });
});
