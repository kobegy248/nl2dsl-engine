import { Card, Alert } from 'antd';

export default function PermissionTable() {
  return (
    <Card>
      <Alert
        message="权限配置"
        description="当前从 configs/permissions.yaml 加载，仅支持只读展示。在线编辑功能后续开发。"
        type="info"
        showIcon
      />
      <div className="mt-4 text-gray-400">权限配置内容展示待后端 API 支持后实现</div>
    </Card>
  );
}
