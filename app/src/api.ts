import type { LatLng } from './components/MapView/MapView.types';
import type { ReportFormData } from './components/ReportModal/ReportModal.types';

const API_URL = (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000';

export interface ReportStatus {
  event_id: string;
  status: 'processing' | 'rejected' | 'routed' | 'resolved' | 'fined' | 'paid';
  case_id?: string;
  authority?: string;
  reports_on_case?: number;
  sla_due_at?: string;
  under_review?: boolean;
  reasons?: string[];
}

async function check(response: Response): Promise<Response> {
  if (!response.ok) throw new Error(`API ${response.status}: ${await response.text()}`);
  return response;
}

export async function registerReporter(displayName: string, email: string): Promise<string> {
  const response = await fetch(`${API_URL}/reporters`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName, email }),
  });
  const body = (await (await check(response)).json()) as { reporter_id: string };
  return body.reporter_id;
}

/** The Idempotency-Key makes a retried submission (flaky mobile network) count once. */
export async function submitReport(
  reporterId: string,
  form: ReportFormData,
  location: LatLng,
  photos: File[],
  idempotencyKey: string,
): Promise<string> {
  const data = new FormData();
  data.append(
    'report',
    JSON.stringify({
      reporter_id: reporterId,
      category: form.category,
      lat: location.lat,
      lon: location.lng,
      description: form.description || undefined,
      plate: form.plate || undefined,
      occurred_at: new Date().toISOString(),
      app_version: 'web-0.1',
    }),
  );
  photos.forEach((photo) => data.append('photos', photo));
  const response = await fetch(`${API_URL}/reports`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: data,
  });
  const body = (await (await check(response)).json()) as { event_id: string };
  return body.event_id;
}

export interface CategoryRouting {
  category: string;
  authority: string;
  sla_hours: number;
}

/** Today's routing rules, read from the same versioned table the stream processor uses. */
export async function getCategoryRouting(): Promise<CategoryRouting[]> {
  const response = await fetch(`${API_URL}/categories`);
  return (await (await check(response)).json()) as CategoryRouting[];
}

export async function getReportStatus(eventId: string): Promise<ReportStatus> {
  const response = await fetch(`${API_URL}/reports/${eventId}`);
  return (await (await check(response)).json()) as ReportStatus;
}
