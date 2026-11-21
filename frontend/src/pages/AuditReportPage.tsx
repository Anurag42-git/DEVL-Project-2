import { useQuery } from '@tanstack/react-query';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { FileCode2, FileSpreadsheet, FileText, Printer } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { ErrorState, PageHeader } from '@/components/shared/States';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { dateTime, number, percent } from '@/lib/format';

const downloads = [
  { format: 'md' as const, label: 'Markdown', icon: FileText },
  { format: 'html' as const, label: 'HTML', icon: FileCode2 },
  { format: 'csv' as const, label: 'Review queue CSV', icon: FileSpreadsheet },
];

export function AuditReportPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['report'], queryFn: api.report,
  });

  return (
    <>
      <PageHeader
        title="Audit Report"
        description="Methodology, validation findings, reconciliation adjustments, review outcomes and detection quality in one reproducible document."
        actions={
          <div className="no-print flex flex-wrap gap-2">
            {downloads.map((item) => (
              <a key={item.format} href={api.downloadUrl(item.format)} download>
                <Button variant="outline" size="sm">
                  <item.icon className="h-4 w-4" /> {item.label}
                </Button>
              </a>
            ))}
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer className="h-4 w-4" /> Print
            </Button>
          </div>
        }
      />

      {isError ? <Card><ErrorState message={error.message} onRetry={() => void refetch()} /></Card> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {data?.detection_quality ? [
              { label: 'Recall on injected issues', value: percent(data.detection_quality.recall) },
              { label: 'Precision (all flags)', value: percent(data.detection_quality.precision) },
              { label: 'Injected issue pairs', value: number(data.detection_quality.expected_pairs) },
              { label: 'Generated', value: dateTime(data.generated_at) },
            ].map((item) => (
              <Card key={item.label} className="p-4">
                <p className="text-xs text-muted">{item.label}</p>
                <p className="num mt-2 text-lg font-semibold text-ink">{item.value}</p>
              </Card>
            )) : Array.from({ length: 4 }).map((_, index) => (
              <Card key={index} className="p-4"><Skeleton className="h-3 w-24" /><Skeleton className="mt-3 h-6 w-20" /></Card>
            ))}
          </div>

          {isLoading || !data ? (
            <Card className="space-y-3 p-6">
              <Skeleton className="h-5 w-64" /><Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" /><Skeleton className="h-4 w-4/6" />
            </Card>
          ) : (
            <>
              <div className="no-print flex flex-wrap gap-2">
                {data.sections.map((section) => (
                  <a key={section.title} href={`#section-${section.title.replace(/\W+/g, '-')}`}
                    className="rounded-lg border border-line bg-surface px-2.5 py-1 text-[11px] text-muted transition-colors hover:border-accent/50 hover:text-ink">
                    {section.title}
                  </a>
                ))}
              </div>
              {data.sections.map((section) => (
                <Card key={section.title} id={`section-${section.title.replace(/\W+/g, '-')}`}>
                  <CardHeader><CardTitle className="text-base">{section.title}</CardTitle></CardHeader>
                  <CardContent className="report-body">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{section.body}</ReactMarkdown>
                  </CardContent>
                </Card>
              ))}
            </>
          )}
        </div>
      )}
    </>
  );
}
