import { Table } from 'antd';
import type { ColumnsType } from 'antd/es/table';

interface Props {
  data: Record<string, unknown>[];
}

export default function ResultTable({ data }: Props) {
  if (!data || data.length === 0) {
    return <div className="text-gray-400 text-center py-8">暂无数据</div>;
  }

  const columns: ColumnsType<Record<string, unknown>> = Object.keys(data[0]).map((key) => ({
    title: key,
    dataIndex: key,
    key,
    ellipsis: true,
  }));

  return (
    <Table
      dataSource={data.map((row, i) => ({ ...row, key: i }))}
      columns={columns}
      pagination={{ pageSize: 10 }}
      size="small"
      scroll={{ x: 'max-content' }}
    />
  );
}
