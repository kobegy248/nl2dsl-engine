import { useState } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { Menu } from 'antd';
import MetricTable from '../components/admin/MetricTable';
import AuditLogTable from '../components/admin/AuditLogTable';
import AuditTraceDetail from '../components/admin/AuditTraceDetail';
import PermissionTable from '../components/admin/PermissionTable';

export default function AdminPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [detailId, setDetailId] = useState<string | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const handleViewDetail = (id: string) => {
    setDetailId(id);
    setDetailOpen(true);
  };

  const menuItems = [
    { key: '/admin/metrics', label: '指标管理' },
    { key: '/admin/audit', label: '审计日志' },
    { key: '/admin/permissions', label: '权限配置' },
  ];

  return (
    <div className="page-container">
      <Menu
        mode="horizontal"
        selectedKeys={[location.pathname]}
        items={menuItems}
        onClick={({ key }) => navigate(key)}
        className="mb-4"
      />
      <Routes>
        <Route index element={<MetricTable />} />
        <Route path="metrics" element={<MetricTable />} />
        <Route path="audit" element={<AuditLogTable onViewDetail={handleViewDetail} />} />
        <Route path="permissions" element={<PermissionTable />} />
      </Routes>
      <AuditTraceDetail
        id={detailId}
        open={detailOpen}
        onClose={() => setDetailOpen(false)}
      />
    </div>
  );
}
