import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from './Layout';
import QueryPage from './pages/QueryPage';
import AdminPage from './pages/AdminPage';
import { TenantProvider } from './context/TenantContext';

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <TenantProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Layout />}>
              <Route index element={<Navigate to="/query" replace />} />
              <Route path="query" element={<QueryPage />} />
              <Route path="admin/*" element={<AdminPage />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </TenantProvider>
    </QueryClientProvider>
  );
}
