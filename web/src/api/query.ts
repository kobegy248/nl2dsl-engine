import { client } from './client';
import type { QueryRequest, QueryResponse, DSL } from '../types/api';

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
