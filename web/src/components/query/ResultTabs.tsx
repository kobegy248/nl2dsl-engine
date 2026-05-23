import { useState } from 'react';
import { Tabs, Button } from 'antd';
import DSLViewer from './DSLViewer';
import SQLPreviewModal from './SQLPreviewModal';
import TracePanel from './TracePanel';
import type { DSL, TraceStep } from '../../types/api';

interface Props {
  dsl: DSL;
  sql: string;
  trace: TraceStep[];
}

export default function ResultTabs({ dsl, sql, trace }: Props) {
  const [sqlModalOpen, setSqlModalOpen] = useState(false);

  const items = [
    {
      key: 'dsl',
      label: 'DSL',
      children: <DSLViewer dsl={dsl} />,
    },
    {
      key: 'sql',
      label: (
        <span>
          SQL{' '}
          <Button size="small" type="link" onClick={(e) => { e.stopPropagation(); setSqlModalOpen(true); }}>
            查看
          </Button>
        </span>
      ),
      children: (
        <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto' }}>
          <code>{sql}</code>
        </pre>
      ),
    },
    {
      key: 'trace',
      label: '执行链路',
      children: <TracePanel steps={trace} />,
    },
  ];

  return (
    <>
      <Tabs items={items} />
      <SQLPreviewModal sql={sql} open={sqlModalOpen} onClose={() => setSqlModalOpen(false)} />
    </>
  );
}
