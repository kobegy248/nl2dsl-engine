import { Timeline, Tag } from 'antd';

interface Props {
  steps: { step: string; status: string; duration_ms?: number }[];
}

const statusColor: Record<string, string> = {
  success: 'green',
  error: 'red',
  pending: 'blue',
};

export default function TracePanel({ steps }: Props) {
  return (
    <Timeline
      items={steps.map((s) => ({
        color: statusColor[s.status] || 'gray',
        children: (
          <div>
            <Tag color={statusColor[s.status]}>{s.status}</Tag>
            <span className="font-medium">{s.step}</span>
            {s.duration_ms && (
              <span className="text-gray-400 text-sm ml-2">({s.duration_ms}ms)</span>
            )}
          </div>
        ),
      }))}
    />
  );
}
