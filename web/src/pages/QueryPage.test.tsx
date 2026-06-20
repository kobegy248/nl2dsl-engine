import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

const queryMock = vi.fn();
const warningMock = vi.fn();

vi.mock('../api/query', () => ({
  queryAPI: { query: (...args: unknown[]) => queryMock(...args) },
}));

vi.mock('../context/TenantContext', () => ({
  useTenant: () => ({ tenantId: 't001', ready: true, setTenantId: vi.fn() }),
}));

vi.mock('antd', () => ({
  Alert: ({ message }: { message: string }) => <div data-testid="warning-alert">{message}</div>,
  Card: ({ children }: { children: React.ReactNode }) => <section>{children}</section>,
  Segmented: () => <div />,
  message: { error: vi.fn(), warning: (...args: unknown[]) => warningMock(...args) },
}));

vi.mock('../components/query/QueryInput', () => ({
  default: ({ onSubmit }: { onSubmit: (question: string) => void }) => (
    <button onClick={() => onSubmit('按地区查询销售额')}>run-query</button>
  ),
}));
vi.mock('../components/query/ResultTable', () => ({
  default: ({ data }: { data: Record<string, unknown>[] }) => (
    <div data-testid="result-row-count">{data.length}</div>
  ),
}));
vi.mock('../components/query/ResultChart', () => ({ default: () => <div /> }));
vi.mock('../components/query/ResultTabs', () => ({ default: () => <div /> }));
vi.mock('../components/query/QueryProgress', () => ({ default: () => <div /> }));
vi.mock('../components/common/Loading', () => ({ default: () => <div /> }));
vi.mock('../components/common/ErrorAlert', () => ({
  default: ({ message }: { message: string }) => <div data-testid="error">{message}</div>,
}));

import QueryPage from './QueryPage';

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

describe('QueryPage warning responses', () => {
  let root: Root;
  let container: HTMLDivElement;

  beforeEach(() => {
    queryMock.mockReset();
    warningMock.mockReset();
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  it('renders rows returned with a non-blocking warning', async () => {
    queryMock.mockResolvedValue({
      data: {
        status: 'warning',
        data: [{ sales_amount: 100 }, { sales_amount: 80 }, { sales_amount: 60 }],
        dsl: {
          data_source: 'orders',
          metrics: [{ func: 'sum', field: 'pay_amount', alias: 'sales_amount' }],
        },
        sql: 'SELECT SUM(pay_amount) FROM orders',
        execution_time_ms: 12,
      },
    });

    await act(async () => {
      root.render(<QueryPage />);
    });
    const button = container.querySelector('button');
    expect(button).not.toBeNull();

    await act(async () => {
      button!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      await flushPromises();
    });

    expect(container.querySelector('[data-testid="result-row-count"]')?.textContent).toBe('3');
    expect(container.querySelector('[data-testid="error"]')).toBeNull();
    expect(container.querySelector('[data-testid="warning-alert"]')).not.toBeNull();
    expect(warningMock).toHaveBeenCalled();
  });
});
