import { Drawer, Timeline, Tag } from 'antd';
import Loading from '../common/Loading';
import JsonViewer from '../common/JsonViewer';
import { useAuditDetail } from '../../hooks/useAudit';
import type { TraceStep } from '../../types/api';

interface Props {
  id: string | null;
  open: boolean;
  onClose: () => void;
}

const statusColor: Record<string, string> = {
  success: 'green',
  error: 'red',
  pending: 'blue',
};

export default function AuditTraceDetail({ id, open, onClose }: Props) {
  const { data, isLoading } = useAuditDetail(id || '');

  return (
    <Drawer title="审计详情" width={720} open={open} onClose={onClose}>
      {isLoading && <Loading />}
      {data && (
        <div className="space-y-4">
          <div>
            <h3 className="font-medium">查询</h3>
            <p>{data.question}</p>
          </div>

          <div>
            <h3 className="font-medium">状态</h3>
            <Tag color={statusColor[data.status] || 'default'}>{data.status}</Tag>
          </div>

          <div>
            <h3 className="font-medium">SQL</h3>
            <pre className="bg-gray-100 p-2 rounded text-sm overflow-auto">{data.sql}</pre>
          </div>

          <div>
            <h3 className="font-medium">DSL</h3>
            <JsonViewer data={data.dsl} />
          </div>

          <div>
            <h3 className="font-medium">执行链路</h3>
            <Timeline
              items={(data.trace || []).map((t: TraceStep) => ({
                color: statusColor[t.status] || 'gray',
                children: (
                  <div>
                    <Tag color={statusColor[t.status]}>{t.status}</Tag>
                    <span className="font-medium">{t.step}</span>
                    {t.duration_ms && <span className="text-gray-400 text-sm ml-2">({t.duration_ms}ms)</span>}
                  </div>
                ),
              }))}
            />
          </div>
        </div>
      )}
    </Drawer>
  );
}
