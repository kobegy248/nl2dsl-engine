import { client } from './client';
import type { SchemaResponse } from '../types/api';

export const schemaAPI = {
  getSchema: () => client.get<SchemaResponse>('/api/v1/schema'),
  getMetrics: () => client.get<Record<string, unknown>>('/api/v1/metrics'),
};
