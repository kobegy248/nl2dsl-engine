import { createContext, useContext, useMemo, useState, type ReactNode } from 'react';

/**
 * 统一租户上下文（第三轮审阅 P1）。
 *
 * 项目尚无正式认证授权框架。当前以单一租户来源为底线，避免在多个文件中
 * 硬编码 tenant_id：QueryPage、AdminPage（审计列表/详情）均从此处读取，
 * 后续接入正式身份后只需替换本模块的实现。
 */

interface TenantContextValue {
  /** 当前选中的租户 ID；未就绪时为空字符串，查询方据此不发请求。 */
  tenantId: string;
  setTenantId: (id: string) => void;
  /** 是否就绪（非空且非全空白）。 */
  ready: boolean;
}

const TenantContext = createContext<TenantContextValue | null>(null);

const DEFAULT_TENANT_ID = 'default';

export function TenantProvider({ children }: { children: ReactNode }) {
  const [tenantId, setTenantId] = useState<string>(DEFAULT_TENANT_ID);
  const value = useMemo<TenantContextValue>(
    () => ({
      tenantId,
      setTenantId,
      ready: !!tenantId && tenantId.trim().length > 0,
    }),
    [tenantId],
  );
  return <TenantContext.Provider value={value}>{children}</TenantContext.Provider>;
}

export function useTenant(): TenantContextValue {
  const ctx = useContext(TenantContext);
  if (ctx === null) {
    // Provider 未挂载时回退到默认租户，保持旧调用方可用，但给出明确默认值，
    // 不在调用处再各自硬编码。
    return {
      tenantId: DEFAULT_TENANT_ID,
      setTenantId: () => {},
      ready: true,
    };
  }
  return ctx;
}
