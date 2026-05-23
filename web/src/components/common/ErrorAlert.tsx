import { Alert } from 'antd';

interface Props {
  message: string;
  onRetry?: () => void;
}

export default function ErrorAlert({ message, onRetry }: Props) {
  return (
    <Alert
      message="请求失败"
      description={message}
      type="error"
      showIcon
      action={
        onRetry ? (
          <button
            onClick={onRetry}
            className="text-blue-500 hover:text-blue-700 text-sm"
          >
            重试
          </button>
        ) : undefined
      }
    />
  );
}
