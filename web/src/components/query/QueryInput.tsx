import { useState } from 'react';
import { Input, Button } from 'antd';
import { SendOutlined } from '@ant-design/icons';

interface Props {
  onSubmit: (question: string) => void;
  loading?: boolean;
}

export default function QueryInput({ onSubmit, loading }: Props) {
  const [question, setQuestion] = useState('');

  const handleSubmit = () => {
    if (!question.trim() || loading) return;
    onSubmit(question.trim());
  };

  return (
    <div className="flex gap-2">
      <Input.TextArea
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="输入自然语言查询，例如：查询华东地区销售额最高的 10 个产品"
        autoSize={{ minRows: 1, maxRows: 3 }}
        onPressEnter={(e) => {
          if (!e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        disabled={loading}
      />
      <Button
        type="primary"
        icon={<SendOutlined />}
        onClick={handleSubmit}
        loading={loading}
        disabled={!question.trim()}
      >
        查询
      </Button>
    </div>
  );
}
