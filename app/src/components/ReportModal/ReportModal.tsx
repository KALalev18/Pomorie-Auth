import { useEffect, useRef, type FormEvent } from 'react';
import { useForm } from '../../hooks/useForm';
import { REPORT_CATEGORIES, type ReportFormData, type ReportModalProps } from './ReportModal.types';

const INITIAL_FORM: ReportFormData = {
  category: '',
  description: '',
  contactEmail: '',
};

export default function ReportModal({ isOpen, location, onClose, onSubmit }: ReportModalProps) {
  const { values, handleChange, reset } = useForm<ReportFormData>(INITIAL_FORM);
  const firstInputRef = useRef<HTMLSelectElement>(null);

  /* focus first field when modal opens */
  useEffect(() => {
    if (isOpen) {
      const raf = requestAnimationFrame(() => firstInputRef.current?.focus());
      return () => cancelAnimationFrame(raf);
    }
  }, [isOpen]);

  /* close on Escape */
  useEffect(() => {
    if (!isOpen) return;
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, [isOpen, onClose]);

  function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    onSubmit(values);
    reset();
    onClose();
  }

  if (!isOpen) return null;

  return (
    /* backdrop */
    <div
      aria-modal="true"
      role="dialog"
      aria-labelledby="modal-title"
      className="animate-fade-in fixed inset-0 z-40 flex items-end justify-center p-4 sm:items-center"
    >
      {/* dim overlay */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* panel */}
      <div className="animate-slide-up relative w-full max-w-md rounded-3xl border border-white/20 bg-slate-900/85 p-6 shadow-2xl backdrop-blur-xl">
        {/* header */}
        <div className="mb-5 flex items-start justify-between">
          <div>
            <h2 id="modal-title" className="text-base font-bold text-white">
              Подай доклад
            </h2>
            {location && (
              <p className="mt-0.5 text-[11px] text-white/40">
                {location.lat.toFixed(5)}, {location.lng.toFixed(5)}
              </p>
            )}
          </div>
          <button
            aria-label="Затвори"
            onClick={onClose}
            className="cursor-pointer rounded-xl p-1.5 text-white/40 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18 18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4" noValidate>

          <Field label="Категория" htmlFor="category" required>
            <select
              id="category"
              name="category"
              ref={firstInputRef}
              value={values.category}
              onChange={handleChange}
              required
              className={inputClass}
            >
              <option value="" disabled>Изберете категория…</option>
              {REPORT_CATEGORIES.map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          </Field>

          <Field label="Описание" htmlFor="description" required>
            <textarea
              id="description"
              name="description"
              value={values.description}
              onChange={handleChange}
              required
              rows={3}
              placeholder="Опишете проблема накратко…"
              className={`${inputClass} resize-none`}
            />
          </Field>

          <Field label="Имейл за обратна връзка" htmlFor="contactEmail">
            <input
              type="email"
              id="contactEmail"
              name="contactEmail"
              value={values.contactEmail}
              onChange={handleChange}
              placeholder="you@example.com"
              className={inputClass}
            />
          </Field>

          {/* actions */}
          <div className="mt-1 flex gap-2">
            <button
              type="button"
              onClick={onClose}
              className="flex-1 cursor-pointer rounded-xl border border-white/15 px-4 py-2.5 text-xs font-semibold text-white/60 transition hover:bg-white/10 hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/30"
            >
              Отказ
            </button>
            <button
              type="submit"
              className="flex-1 cursor-pointer rounded-xl bg-gradient-to-r from-sky-500 to-indigo-500 px-4 py-2.5 text-xs font-semibold text-white shadow-lg transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              Изпрати
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

/* ─── helpers ─── */

const inputClass =
  'w-full rounded-xl border border-white/20 bg-white/10 px-3 py-2.5 text-xs text-white placeholder:text-white/30 focus:border-sky-400/60 focus:outline-none focus:ring-2 focus:ring-sky-400/30 transition';

function Field({
  label,
  htmlFor,
  required = false,
  children,
}: {
  label: string;
  htmlFor: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-[11px] font-semibold uppercase tracking-wider text-white/50">
        {label}
        {required && <span className="ml-0.5 text-sky-400">*</span>}
      </label>
      {children}
    </div>
  );
}
