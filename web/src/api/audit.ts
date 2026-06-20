import { client } from './client';
import type { AuditListResponse, AuditDetailResponse } from '../types/api';

export interface AuditListParams {
  tenant_id: string;
  limit?: number;
  offset?: number;
  status?: string;
  user_id?: string;
}

export const auditAPI = {
  /**
   * 审计列表（第三轮审阅 P1）：后端强制非空 tenant_id。
   * 调用方负责传入当前租户上下文；未就绪时不应调用。
   */
  list: (params: AuditListParams) =>
    client.get<AuditListResponse>('/api/v1/admin/audit/queries', { params }),

  /** 审计详情同样强制 tenant_id。 */
  detail: (id: string, tenant_id: string) =>
    client.get<AuditDetailResponse>(`/api/v1/admin/audit/queries/${id}`, {
      params: { tenant_id },
    }),
};
