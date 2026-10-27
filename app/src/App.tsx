import { useState, useCallback } from 'react';
import NavBar from './components/NavBar/NavBar';
import MapView from './components/MapView/MapView';
import Toast from './components/Toast/Toast';
import ReportModal from './components/ReportModal/ReportModal';
import MyReports, { type SubmittedReport } from './components/MyReports/MyReports';
import { registerReporter, submitReport } from './api';
import type { LatLng } from './components/MapView/MapView.types';
import type { ReportFormData } from './components/ReportModal/ReportModal.types';
import type { NavUser } from './components/NavBar/NavBar.types';

const MOCK_USER: NavUser = {
  name: 'Демо Потребител',
  email: 'demo.user@example.com',
};

const REPORTER_KEY = 'pomorie.reporterId';
const REPORTS_KEY = 'pomorie.reports';
const OUTSIDE_MESSAGE =
  'Докладите са ограничени до територията на Община Поморие. Моля, изберете точка в рамките на общината.';

/* localStorage can be unavailable (private mode); the app still works without it. */
function load<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* not persisted; fine for a demo session */
  }
}

export default function App() {
  const [user, setUser] = useState<NavUser | undefined>(MOCK_USER);
  const [markerPosition, setMarkerPosition] = useState<LatLng | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [toast, setToast] = useState<{ message: string; tone: 'warning' | 'success' } | null>(null);
  const [myReports, setMyReports] = useState<SubmittedReport[]>(() => load(REPORTS_KEY, []));
  const [myReportsOpen, setMyReportsOpen] = useState(false);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [hintDismissed, setHintDismissed] = useState(false);

  const handleInsideClick = useCallback((latLng: LatLng) => {
    setMarkerPosition(latLng);
    setModalOpen(true);
    setHintDismissed(true);
  }, []);

  const handleOutsideClick = useCallback(() => {
    setToast({ message: OUTSIDE_MESSAGE, tone: 'warning' });
  }, []);

  const handleModalClose = useCallback(() => {
    setModalOpen(false);
    setMarkerPosition(null);
  }, []);

  const handleReportSubmit = useCallback(
    async (data: ReportFormData, photos: File[]) => {
      if (!markerPosition) return;
      let reporterId = load<string | null>(REPORTER_KEY, null);
      if (!reporterId) {
        reporterId = await registerReporter(MOCK_USER.name, MOCK_USER.email);
        save(REPORTER_KEY, reporterId);
      }
      const eventId = await submitReport(reporterId, data, markerPosition, photos, crypto.randomUUID());
      const entry = { eventId, category: data.category, submittedAt: new Date().toISOString() };
      setMyReports((previous) => {
        const next = [entry, ...previous];
        save(REPORTS_KEY, next);
        return next;
      });
      setToast({ message: 'Докладът е приет. Следете статуса в „Доклади“.', tone: 'success' });
    },
    [markerPosition],
  );

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-slate-950">

      {/* ── full-screen map ── */}
      <div className="absolute inset-0">
        <MapView
          onInsideClick={handleInsideClick}
          onOutsideClick={handleOutsideClick}
          markerPosition={markerPosition}
        />
      </div>

      {/* ── nav bar ── */}
      <NavBar
        user={user}
        onAboutUs={() => setAboutOpen(true)}
        onReports={() => setMyReportsOpen(true)}
        onSignIn={() => setUser(MOCK_USER)}
        onSignOut={() => setUser(undefined)}
      />

      {/* ── click-to-report hint pill ── */}
      {!hintDismissed && (
        <div className="animate-fade-in pointer-events-none absolute bottom-10 left-1/2 z-20 -translate-x-1/2">
          <div className="flex items-center gap-2.5 rounded-2xl border border-white/20 bg-slate-900/70 px-5 py-3 shadow-xl backdrop-blur-md">
            <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-sky-500/20 text-sky-400">
              <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
              </svg>
            </span>
            <p className="text-xs font-medium text-white/70">
              Натиснете върху картата в <span className="font-semibold text-white">Поморие</span>, за да подадете доклад
            </p>
          </div>
        </div>
      )}

      {/* ── report modal ── */}
      <ReportModal
        isOpen={modalOpen}
        location={markerPosition}
        onClose={handleModalClose}
        onSubmit={handleReportSubmit}
      />

      {/* ── outside-area toast ── */}
      <Toast
        message={toast?.message ?? ''}
        tone={toast?.tone}
        visible={toast !== null}
        onDismiss={() => setToast(null)}
      />

      {myReportsOpen && <MyReports reports={myReports} onClose={() => setMyReportsOpen(false)} />}

      {/* ── about us overlay ── */}
      {aboutOpen && (
        <div
          aria-modal="true"
          role="dialog"
          aria-labelledby="about-title"
          className="animate-fade-in fixed inset-0 z-40 flex items-center justify-center p-4"
        >
          <div
            className="absolute inset-0 bg-black/50 backdrop-blur-sm"
            onClick={() => setAboutOpen(false)}
            aria-hidden="true"
          />
          <div className="animate-slide-up relative w-full max-w-sm rounded-3xl border border-white/20 bg-slate-900/90 p-8 shadow-2xl backdrop-blur-xl">
            {/* logo */}
            <div className="mb-5 flex flex-col items-center gap-3">
              <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-sky-400 to-indigo-500 shadow-lg">
                <svg className="h-7 w-7 text-white" fill="none" viewBox="0 0 24 24" strokeWidth={1.8} stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 10.5c0 7.142-7.5 11.25-7.5 11.25S4.5 17.642 4.5 10.5a7.5 7.5 0 1 1 15 0Z" />
                </svg>
              </span>
              <h2 id="about-title" className="text-lg font-bold text-white">
                Pomorie<span className="font-light opacity-60">Reports</span>
              </h2>
            </div>

            <p className="text-center text-sm leading-relaxed text-white/60">
              Гражданска платформа за сигнализиране на проблеми в Община Поморие.
              Помогни ни да направим града по-добро място за живеене.
            </p>

            <div className="mt-5 grid grid-cols-3 gap-3 border-y border-white/10 py-5">
              {[
                { label: 'Доклади', value: '0' },
                { label: 'Решени', value: '0' },
                { label: 'Граждани', value: '0' },
              ].map(({ label, value }) => (
                <div key={label} className="flex flex-col items-center gap-0.5">
                  <span className="text-xl font-bold text-white">{value}</span>
                  <span className="text-[11px] text-white/40">{label}</span>
                </div>
              ))}
            </div>

            <button
              onClick={() => setAboutOpen(false)}
              className="mt-5 w-full cursor-pointer rounded-xl bg-gradient-to-r from-sky-500 to-indigo-500 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:opacity-90"
            >
              Затвори
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
