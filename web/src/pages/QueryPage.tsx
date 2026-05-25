import { useState } from 'react';
import { Card, message, Segmented } from 'antd';
import QueryInput from '../components/query/QueryInput';
import ResultTable from '../components/query/ResultTable';
import ResultChart from '../components/query/ResultChart';
import ResultTabs from '../components/query/ResultTabs';
import QueryProgress from '../components/query/QueryProgress';
import Loading from '../components/common/Loading';
import ErrorAlert from '../components/common/ErrorAlert';
import { queryAPI } from '../api/query';
import type { QueryResponse } from '../types/api';

export default function QueryPage() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [viewType, setViewType] = useState<'table' | 'bar' | 'line'>('table');
  const [progressEvents, setProgressEvents] = useState<{ node: string; status: string }[]>([]);

  const handleQuery = async (question: string) => {
    setLoading(true);
    setError(null);
    setResult(null);
    setProgressEvents([
      { node: 'clarification', status: 'pending' },
      { node: 'dsl', status: 'pending' },
    ]);

    try {
      const { data } = await queryAPI.query({
        question,
        user_id: 'web_user',
        tenant_id: 'default',
      });
      if (data.status !== 'success' || !data.data) {
        throw new Error(data.status === 'clarification' ? '查询存在歧义' : '查询执行失败，请重试');
      }
      setResult(data);
      setProgressEvents([
        { node: 'clarification', status: 'success' },
        { node: 'dsl', status: 'success' },
        { node: 'validate', status: 'success' },
        { node: 'permission', status: 'success' },
        { node: 'build_sql', status: 'success' },
        { node: 'execute', status: 'success' },
      ]);
    } catch (err) {
      const msg = err instanceof Error ? err.message : '查询失败';
      setError(msg);
      message.error(msg);
      setProgressEvents([
        { node: 'clarification', status: 'success' },
        { node: 'dsl', status: 'error' },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page-container space-y-4">
      <Card>
        <QueryInput onSubmit={handleQuery} loading={loading} />
      </Card>

      {loading && progressEvents.length > 0 && (
        <Card>
          <QueryProgress events={progressEvents} />
        </Card>
      )}
      {loading && progressEvents.length === 0 && <Loading tip="正在查询..." />}
      {error && <ErrorAlert message={error} onRetry={() => handleQuery('retry')} />}

      {result && (
        <>
          {result.data && (
            <Card
              title={
                <div className="flex justify-between items-center">
                  <span>查询结果（{result.data.length} 条，耗时 {result.execution_time_ms}ms）</span>
                  <Segmented
                    options={[
                      { label: '表格', value: 'table' },
                      { label: '柱状图', value: 'bar' },
                      { label: '折线图', value: 'line' },
                    ]}
                    value={viewType}
                    onChange={(v) => setViewType(v as typeof viewType)}
                  />
                </div>
              }
            >
              {viewType === 'table' && <ResultTable data={result.data} />}
              {viewType !== 'table' && result.dsl?.dimensions?.[0] && result.dsl?.metrics?.[0] && (
                <ResultChart
                  data={result.data}
                  xField={result.dsl.dimensions[0]}
                  yField={result.dsl.metrics[0].alias || result.dsl.metrics[0].field}
                  chartType={viewType}
                />
              )}
            </Card>
          )}
          {result.dsl && (
            <Card className="mt-4">
              <ResultTabs
                dsl={result.dsl}
                sql={result.sql}
                trace={[]}
              />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
