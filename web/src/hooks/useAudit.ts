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
