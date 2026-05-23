import { Steps } from 'antd';

interface Props {
  events: { node: string; status: string }[];
}

const nodeLabels: Record<string, string> = {
  clarification: '歧义检测',
  dsl: 'DSL生成',
  validate: '校验',
  permission: '权限',
  build_sql: '构建SQL',
  scan: '扫描',
  sandbox: '沙箱',
  execute: '执行',
};

export default function QueryProgress({ events }: Props) {
  const nodes = ['clarification', 'dsl', 'validate', 'permission', 'build_sql', 'scan', 'sandbox', 'execute'];

  const items = nodes.map((n) => {
    const event = events.find((e) => e.node === n);
    let status: 'wait' | 'process' | 'finish' | 'error' = 'wait';
    if (event?.status === 'success') status = 'finish';
    else if (event?.status === 'error') status = 'error';
    else if (event?.status === 'pending') status = 'process';

    return {
      title: nodeLabels[n] || n,
      status,
    };
  });

  return (
    <Steps
      current={items.findIndex((i) => i.status === 'process')}
      size="small"
      items={items}
      direction="horizontal"
    />
  );
}
