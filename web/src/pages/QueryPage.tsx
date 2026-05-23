import { useState } from 'react';
import { Card, message } from 'antd';
import QueryInput from '../components/query/QueryInput';
import ResultTable from '../components/query/ResultTable';
import Loading from '../components/common/Loading';
import ErrorAlert from '../components/common/ErrorAlert';
import { queryAPI } from '../api/query';
import type { QueryResponse } from '../types/api';

export default function QueryPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleQuery = async (question: string) => {
    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const { data } = await queryAPI.query({
        question,
        user_id: 'web_user',
        tenant_id: 'default',
      });
      setResult(data);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '查询失败';
      setError(msg);
      message.error(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container space-y-4">
      <Card>
        <QueryInput onSubmit={handleQuery} loading={loading} />
      </Card>

      {loading && <Loading tip="正在查询..." />}
      {error && <ErrorAlert message={error} onRetry={() => result && handleQuery(result.dsl ? 'retry' : '')} />}

      {result && (
        <Card title={`查询结果（${result.data.length} 条，耗时 ${result.execution_time_ms}ms）`}>
          <ResultTable data={result.data} />
        </Card>
      )}
    </div>
  );
}
