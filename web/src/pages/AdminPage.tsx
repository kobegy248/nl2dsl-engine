import { useState } from 'react';
import { Menu } from 'antd';
import MetricTable from '../components/admin/MetricTable';
import AuditLogTable from '../components/admin/AuditLogTable';
import AuditTraceDetail from '../components/admin/AuditTraceDetail';
import PermissionTable from '../components/admin/PermissionTable';

type TabKey = 'metrics' | 'audit' | 'permissions';

export default function AdminPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('metrics');
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const handleViewDetail = (id: string) => {
    setDetailId(id);
    setDetailOpen(true);
  };

  const menuItems = [
    { key: 'metrics', label: '指标管理' },
    { key: 'audit', label: '审计日志' },
    { key: 'permissions', label: '权限配置' },
  ];

  return (
    <div className="page-container">
      <Menu
        mode="horizontal"
        selectedKeys={[activeTab]}
        items={menuItems}
        onClick={({ key }) => setActiveTab(key as TabKey)}
        className="mb-4"
      />
      {activeTab === 'metrics' && <MetricTable />}
      {activeTab === 'audit' && <AuditLogTable onViewDetail={handleViewDetail} />}
      {activeTab === 'permissions' && <PermissionTable />}
      <AuditTraceDetail
        id={detailId}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  );
}
