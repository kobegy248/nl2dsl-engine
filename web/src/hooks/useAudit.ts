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
    queryFn: () =>
      auditAPI.detail(id).then((r) => {
        const payload = r.data as { item?: unknown } & Record<string, unknown>;
        // 后端把数据包在 item 字段下，解包以兼容前端旧契约
        return (payload.item ?? payload) as ReturnType<typeof JSON.parse>;
      }),
    enabled: !!id,
  });
}
