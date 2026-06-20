import { useQuery } from '@tanstack/react-query';
import { auditAPI } from '../api/audit';
import { useTenant } from '../context/TenantContext';

/**
 * 审计列表（第三轮审阅 P1）。
 *
 * - tenant_id 来自统一租户上下文，不在本文件硬编码。
 * - queryKey 包含 tenant_id，避免跨租户缓存污染。
 * - tenant_id 未就绪（空）时查询 disabled，不发请求，避免后端 400。
 * - 切换租户后 queryKey 变化，自动发起新请求，不复用其他租户缓存。
 */
export function useAuditList(limit = 20, offset = 0) {
  const { tenantId, ready } = useTenant();
  return useQuery({
    queryKey: ['audit', 'list', tenantId, limit, offset],
    queryFn: () => auditAPI.list({ tenant_id: tenantId, limit, offset }).then((r) => r.data),
    enabled: ready,
  });
}

export function useAuditDetail(id: string) {
  const { tenantId, ready } = useTenant();
  return useQuery({
    queryKey: ['audit', 'detail', tenantId, id],
    queryFn: () =>
      auditAPI.detail(id, tenantId).then((r) => {
        const payload = r.data as unknown as { item?: unknown } & Record<string, unknown>;
        // 后端把数据包在 item 字段下，解包以兼容前端旧契约
        return (payload.item ?? payload) as ReturnType<typeof JSON.parse>;
      }),
    // id 与 tenant_id 都必须就绪才发请求。
    enabled: ready && !!id,
  });
}
