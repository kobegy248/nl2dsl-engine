import { Modal, Typography, Button } from 'antd';
import { CopyOutlined } from '@ant-design/icons';

interface Props {
  sql: string;
  open: boolean;
  onClose: () => void;
}

export default function SQLPreviewModal({ sql, open, onClose }: Props) {
  const handleCopy = () => {
    navigator.clipboard.writeText(sql);
  };

  return (
    <Modal
      title="SQL 预览"
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="copy" icon={<CopyOutlined />} onClick={handleCopy}>
          复制
        </Button>,
        <Button key="close" type="primary" onClick={onClose}>
          关闭
        </Button>,
      ]}
      width={800}
    >
      <Typography.Paragraph>
        <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, overflow: 'auto', maxHeight: 400 }}>
          <code>{sql}</code>
        </pre>
      </Typography.Paragraph>
    </Modal>
  );
}
