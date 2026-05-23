import { Routes, Route } from 'react-router-dom';

function MetricTable() { return <div>指标管理</div>; }
function AuditLogTable() { return <div>审计日志</div>; }
function PermissionTable() { return <div>权限配置</div>; }

export default function AdminPage() {
  return (
    <div className="page-container">
      <Routes>
        <Route index element={<MetricTable />} />
        <Route path="metrics" element={<MetricTable />} />
        <Route path="audit" element={<AuditLogTable />} />
        <Route path="permissions" element={<PermissionTable />} />
      </Routes>
    </div>
  );
}
