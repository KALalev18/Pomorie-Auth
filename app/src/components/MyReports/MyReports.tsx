import { useEffect, useState } from 'react';
import { getReportStatus, type ReportStatus } from '../../api';
import { REPORT_CATEGORIES } from '../ReportModal/ReportModal.types';

export interface SubmittedReport {
  eventId: string;
  category: string;
  submittedAt: string;
}

const POLL_MS = 5000;

const STATUS_LABELS: Record<ReportStatus['status'], string> = {
  processing: 'Обработва се',
  rejected: 'Отхвърлен',
  routed: 'Насочен към институция',
  resolved: 'Решен',
  fined: 'Наложена глоба',
  paid: 'Глобата е платена',
};

const AUTHORITY_LABELS: Record<string, string> = {
  traffic_police: 'Пътна полиция',
  police: 'Полиция',
  municipality_cleanliness: 'Община: чистота',
  municipality_infrastructure: 'Община: инфраструктура',
  municipality_environment: 'Община: екология',
};

function categoryLabel(value: string): string {
  return REPORT_CATEGORIES.find((c) => c.value === value)?.label ?? value;
}

/** The reporter's own reports with live status from the API (polled while open). */
export default function MyReports({ reports, onClose }: { reports: SubmittedReport[]; onClose: () => void }) {
  const [statuses, setStatuses] = useState<Record<string, ReportStatus>>({});

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      const results = await Promise.allSettled(reports.map((r) => getReportStatus(r.eventId)));
      if (cancelled) return;
      const next: Record<string, ReportStatus> = {};
      results.forEach((result) => {
        if (result.status === 'fulfilled') next[result.value.event_id] = result.value;
      });
      setStatuses(next);
    }
    void refresh();
    const timer = setInterval(() => void refresh(), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [reports]);

  return (
    <div role="dialog" aria-modal="true" aria-labelledby="my-reports-title" className="animate-fade-in fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div className="animate-slide-up relative max-h-[80vh] w-full max-w-md overflow-y-auto rounded-3xl border border-white/20 bg-slate-900/90 p-6 shadow-2xl backdrop-blur-xl">
        <h2 id="my-reports-title" className="mb-4 text-base font-bold text-white">Моите доклади</h2>
        {reports.length === 0 && <p className="text-xs text-white/50">Все още нямате подадени доклади.</p>}
        <ul className="flex flex-col gap-2">
          {reports.map((r) => {
            const status = statuses[r.eventId];
            return (
              <li key={r.eventId} className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3">
                <p className="text-xs font-semibold text-white">{categoryLabel(r.category)}</p>
                <p className="mt-0.5 text-[11px] text-white/40">{new Date(r.submittedAt).toLocaleString('bg-BG')}</p>
                <p className="mt-1.5 text-xs text-white/80">
                  {status ? STATUS_LABELS[status.status] : 'Зарежда се…'}
                  {status?.authority && ` · ${AUTHORITY_LABELS[status.authority] ?? status.authority}`}
                  {status?.reports_on_case && status.reports_on_case > 1 && ` · ${status.reports_on_case} сигнала за същия проблем`}
                </p>
                {status?.under_review && <p className="mt-1 text-[11px] text-amber-300">В ръчна проверка</p>}
                {status?.reasons && <p className="mt-1 text-[11px] text-red-300">{status.reasons[0]}</p>}
              </li>
            );
          })}
        </ul>
        <button onClick={onClose} className="mt-5 w-full cursor-pointer rounded-xl bg-gradient-to-r from-sky-500 to-indigo-500 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:opacity-90">
          Затвори
        </button>
      </div>
    </div>
  );
}
