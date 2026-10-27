import { useEffect, useRef, useState, type ChangeEvent, type FormEvent } from 'react';
import { getCategoryRouting, type CategoryRouting } from '../../api';
import { useForm } from '../../hooks/useForm';
import {
  AUTHORITY_LABELS,
  MAX_PHOTOS,
  PLATE_CATEGORIES,
  REPORT_CATEGORIES,
  type ReportFormData,
  type ReportModalProps,
} from './ReportModal.types';

const INITIAL_FORM: ReportFormData = {
  category: '',
  description: '',
  plate: '',
};

export default function ReportModal({ isOpen, location, onClose, onSubmit }: ReportModalProps) {
  const { values, handleChange, reset } = useForm<ReportFormData>(INITIAL_FORM);
  const firstInputRef = useRef<HTMLSelectElement>(null);
  const [photos, setPhotos] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [routing, setRouting] = useState<Record<string, CategoryRouting>>({});

  /* load today's routing rules once, so the reporter sees who will handle the report */
  useEffect(() => {
    if (!isOpen || Object.keys(routing).length) return;
    let cancelled = false;
    getCategoryRouting()
      .then((rules) => {
        if (!cancelled) setRouting(Object.fromEntries(rules.map((r) => [r.category, r])));
      })
      .catch(() => {
        /* the hint is optional; the report can still be sent */
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, routing]);

  const route = routing[values.category];

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

  function handlePhotos(e: ChangeEvent<HTMLInputElement>) {
    setPhotos(Array.from(e.target.files ?? []).slice(0, MAX_PHOTOS));
  }

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!values.category) {
      setError('Изберете категория.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      await onSubmit(values, photos);
      reset();
      setPhotos([]);
      onClose();
    } catch {
      setError('Докладът не беше изпратен. Проверете връзката и опитайте отново.');
    } finally {
      setSubmitting(false);
    }
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
              className={`${inputClass} [color-scheme:dark]`}
            >
              <option value="" disabled className={optionClass}>Изберете категория…</option>
              {REPORT_CATEGORIES.map(({ value, label }) => (
                <option key={value} value={value} className={optionClass}>{label}</option>
              ))}
            </select>
            {route && (
              <p className="text-[11px] text-white/60">
                Насочва се към:{' '}
                <span className="font-semibold text-white">
                  {AUTHORITY_LABELS[route.authority] ?? route.authority}
                </span>{' '}
                · срок за реакция {route.sla_hours} ч
              </p>
            )}
          </Field>

          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3 py-2 text-[11px] text-red-100">
            При спешен случай или опасност за живота звъннете на{' '}
            <a href="tel:112" className="font-bold underline">112</a>. Докладите тук не са за спешни случаи.
          </p>

          <Field label="Описание" htmlFor="description">
            <textarea
              id="description"
              name="description"
              value={values.description}
              onChange={handleChange}
              maxLength={1000}
              rows={3}
              placeholder="Опишете проблема накратко…"
              className={`${inputClass} resize-none`}
            />
          </Field>

          {PLATE_CATEGORIES.has(values.category) && (
            <Field label="Регистрационен номер" htmlFor="plate">
              <input
                id="plate"
                name="plate"
                value={values.plate}
                onChange={handleChange}
                maxLength={16}
                placeholder="А 1234 ВК"
                className={inputClass}
              />
              <p className="text-[11px] text-white/40">
                Номерът се криптира еднопосочно (HMAC) и не се съхранява в явен вид.
              </p>
            </Field>
          )}

          <Field label={`Снимки (до ${MAX_PHOTOS})`} htmlFor="photos">
            <input
              type="file"
              id="photos"
              accept="image/*"
              multiple
              onChange={handlePhotos}
              className={`${inputClass} file:mr-3 file:rounded-lg file:border-0 file:bg-white/15 file:px-2 file:py-1 file:text-white`}
            />
            <p className="text-[11px] text-white/40">
              Метаданните (GPS, устройство) се премахват преди съхранение.
            </p>
          </Field>

          {error && (
            <p role="alert" className="text-xs text-red-300">
              {error}
            </p>
          )}

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
              disabled={submitting}
              className="flex-1 cursor-pointer rounded-xl disabled:cursor-wait disabled:opacity-60 bg-gradient-to-r from-sky-500 to-indigo-500 px-4 py-2.5 text-xs font-semibold text-white shadow-lg transition hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400"
            >
              {submitting ? 'Изпращане…' : 'Изпрати'}
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

/* the native option list ignores the translucent input background, so give it a solid one */
const optionClass = 'bg-slate-900 text-white';

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
