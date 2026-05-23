import { client } from './client';
import type { AuditListResponse, AuditDetailResponse } from '../types/api';

export const auditAPI = {
  list: (params?: { limit?: number; offset?: number; status?: string; user_id?: string }) =>
    client.get<AuditListResponse>('/api/v1/admin/audit/queries', { params }),

  detail: (id: string) =>
    client.get<AuditDetailResponse>(`/api/v1/admin/audit/queries/${id}`),
};
