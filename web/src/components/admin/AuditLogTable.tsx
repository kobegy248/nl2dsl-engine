import { useState } from 'react';
import { Table, Tag, Button } from 'antd';
import Loading from '../common/Loading';
import ErrorAlert from '../common/ErrorAlert';
import { useAuditList } from '../../hooks/useAudit';
import type { AuditItem } from '../../types/api';

interface Props {
  onViewDetail: (id: string) => void;
}

const statusMap: Record<string, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  error: { color: 'red', text: '失败' },
  clarification: { color: 'orange', text: '歧义' },
  pending_review: { color: 'blue', text: '待审核' },
};

export default function AuditLogTable({ onViewDetail }: Props) {
  const [page, setPage] = useState(1);
  const pageSize = 20;
  const { data, isLoading, error, refetch } = useAuditList(pageSize, (page - 1) * pageSize);

  if (isLoading) return <Loading />;
  if (error) return <ErrorAlert message={(error as Error).message} onRetry={refetch} />;

  const columns = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 180 },
    { title: '用户', dataIndex: 'user_id', key: 'user_id', width: 100 },
    { title: '问题', dataIndex: 'question', key: 'question', ellipsis: true },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status: string) => {
        const s = statusMap[status] || { color: 'default', text: status };
        return <Tag color={s.color}>{s.text}</Tag>;
      },
    },
    {
      title: '耗时',
      dataIndex: 'execution_time_ms',
      key: 'execution_time_ms',
      width: 100,
      render: (v: number) => `${v}ms`,
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_: unknown, record: AuditItem) => (
        <Button size="small" type="link" onClick={() => onViewDetail(record.query_id || record.id)}>
          详情
        </Button>
      ),
    },
  ];

  return (
    <Table
      dataSource={data?.items || []}
      columns={columns}
      rowKey={(record) => record.query_id || record.id}
      pagination={{
        current: page,
        pageSize,
        total: data?.total || 0,
        onChange: setPage,
      }}
      size="small"
    />
  );
}
