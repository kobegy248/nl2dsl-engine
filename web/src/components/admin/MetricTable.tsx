import { useQuery } from '@tanstack/react-query';
import { Table } from 'antd';
import Loading from '../common/Loading';
import ErrorAlert from '../common/ErrorAlert';
import { schemaAPI } from '../../api/schema';

export default function MetricTable() {
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ['schema'],
    queryFn: () => schemaAPI.getSchema().then((r) => r.data),
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrorAlert message={(error as Error).message} onRetry={refetch} />;

  const metrics = Object.entries(data?.metrics || {}).map(([name, def]) => ({
    key: name,
    name,
    expr: def.expr,
    description: def.description || '-',
  }));

  const dimensions = Object.entries(data?.dimensions || {}).map(([name, def]) => ({
    key: name,
    name,
    column: def.column,
    description: def.description || '-',
  }));

  const dataSources = Object.entries(data?.data_sources || {}).map(([name, def]) => ({
    key: name,
    name,
    table: def.table,
    metrics: def.metrics,
    dimensions: def.dimensions,
  }));

  return (
    <div className="space-y-6">
      <h2 className="text-lg font-medium">指标定义</h2>
      <Table
        dataSource={metrics}
        columns={[
          { title: '指标名', dataIndex: 'name', key: 'name' },
          { title: '表达式', dataIndex: 'expr', key: 'expr' },
          { title: '说明', dataIndex: 'description', key: 'description' },
        ]}
        size="small"
        pagination={false}
      />

      <h2 className="text-lg font-medium">维度定义</h2>
      <Table
        dataSource={dimensions}
        columns={[
          { title: '维度名', dataIndex: 'name', key: 'name' },
          { title: '对应列', dataIndex: 'column', key: 'column' },
          { title: '说明', dataIndex: 'description', key: 'description' },
        ]}
        size="small"
        pagination={false}
      />

      <h2 className="text-lg font-medium">数据源</h2>
      <Table
        dataSource={dataSources}
        columns={[
          { title: '数据源', dataIndex: 'name', key: 'name' },
          { title: '表名', dataIndex: 'table', key: 'table' },
          { title: '指标数', dataIndex: 'metrics', key: 'metrics', render: (m: string[]) => m.length },
          { title: '维度数', dataIndex: 'dimensions', key: 'dimensions', render: (d: string[]) => d.length },
        ]}
        size="small"
        pagination={false}
      />
    </div>
  );
}
