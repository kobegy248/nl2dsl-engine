import { Typography } from 'antd';

interface Props {
  data: unknown;
}

export default function JsonViewer({ data }: Props) {
  return (
    <Typography.Paragraph>
      <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto', maxHeight: 400 }}>
        <code>{JSON.stringify(data, null, 2)}</code>
      </pre>
    </Typography.Paragraph>
  );
}
