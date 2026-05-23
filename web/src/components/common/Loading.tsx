import { Spin } from 'antd';

interface Props {
  tip?: string;
}

export default function Loading({ tip = '加载中...' }: Props) {
  return (
    <div className="flex justify-center items-center py-12">
      <Spin tip={tip} size="large" />
    </div>
  );
}
