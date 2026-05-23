import { Layout as AntLayout, Menu } from 'antd';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import { SearchOutlined, SettingOutlined } from '@ant-design/icons';

const { Sider, Header, Content } = AntLayout;

export default function Layout() {
  const location = useLocation();
  const navigate = useNavigate();

  const menuItems = [
    { key: '/query', icon: <SearchOutlined />, label: '查询工作台' },
    { key: '/admin', icon: <SettingOutlined />, label: '管理后台' },
  ];

  return (
    <AntLayout style={{ minHeight: '100vh' }}>
      <Sider theme="light" width={200}>
        <div style={{ padding: '16px', fontWeight: 'bold', fontSize: '16px' }}>
          NL2DSL
        </div>
        <Menu
          mode="inline"
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
        />
      </Sider>
      <AntLayout>
        <Header style={{ background: '#fff', padding: '0 24px', display: 'flex', alignItems: 'center' }}>
          <span style={{ fontSize: '16px', fontWeight: 500 }}>
            {location.pathname === '/query' ? '查询工作台' : '管理后台'}
          </span>
        </Header>
        <Content style={{ margin: '16px', background: '#f5f5f5', minHeight: 280 }}>
          <Outlet />
        </Content>
      </AntLayout>
    </AntLayout>
  );
}
