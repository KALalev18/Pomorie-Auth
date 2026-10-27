import { useEffect } from 'react';
import type { ToastProps } from './Toast.types';

const AUTO_DISMISS_MS = 4000;

export default function Toast({ message, tone = 'warning', visible, onDismiss }: ToastProps) {
  useEffect(() => {
    if (!visible) return;
    const timer = setTimeout(onDismiss, AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [visible, onDismiss]);

  if (!visible) return null;

  return (
    <div
      role="alert"
      aria-live="polite"
      className="animate-toast-in fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-2xl border border-white/20 bg-slate-900/80 px-4 py-3.5 shadow-2xl backdrop-blur-xl"
    >
      {/* icon */}
      <span
        className={`mt-0.5 flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full ${
          tone === 'success' ? 'bg-emerald-400/20 text-emerald-400' : 'bg-amber-400/20 text-amber-400'
        }`}
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          {tone === 'success' ? (
            <path strokeLinecap="round" strokeLinejoin="round" d="m4.5 12.75 6 6 9-13.5" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
          )}
        </svg>
      </span>

      {/* message */}
      <p className="flex-1 text-xs leading-relaxed text-white/80">{message}</p>

      {/* dismiss */}
      <button
        aria-label="Затвори известието"
        onClick={onDismiss}
        className="ml-1 flex-shrink-0 cursor-pointer rounded-lg p-1 text-white/40 transition hover:text-white/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  );
}
