import { QueryClient, QueryClientProvider, useMutation, useQueryClient } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { Toaster } from 'sonner';
import { AppShell } from '@/components/layout/AppShell';
import { ThemeProvider, useTheme } from '@/components/layout/ThemeProvider';
import { api } from '@/lib/api';
import { OverviewPage } from '@/pages/OverviewPage';
import { ReviewQueuePage } from '@/pages/ReviewQueuePage';
import { LedgerPage } from '@/pages/LedgerPage';
import { DataQualityPage } from '@/pages/DataQualityPage';
import { AuditReportPage } from '@/pages/AuditReportPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false },
  },
});

function ToasterWithTheme() {
  const { theme } = useTheme();
  return <Toaster theme={theme} position="bottom-right" richColors closeButton />;
}

function Shell() {
  const client = useQueryClient();
  const reload = useMutation({
    mutationFn: api.reload,
    onSuccess: () => {
      void client.invalidateQueries();
    },
  });

  return (
    <AppShell onReload={() => reload.mutate()} reloading={reload.isPending}>
      <Routes>
        <Route path="/" element={<Navigate to="/overview" replace />} />
        <Route path="/overview" element={<OverviewPage />} />
        <Route path="/review" element={<ReviewQueuePage />} />
        <Route path="/ledger" element={<LedgerPage />} />
        <Route path="/data-quality" element={<DataQualityPage />} />
        <Route path="/report" element={<AuditReportPage />} />
        <Route path="*" element={<Navigate to="/overview" replace />} />
      </Routes>
    </AppShell>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <BrowserRouter>
          <ToasterWithTheme />
          <Shell />
        </BrowserRouter>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
