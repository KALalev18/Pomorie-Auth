import type { LatLng } from '../MapView/MapView.types';

export type ReportFormData = {
  category: string;
  description: string;
  plate: string;
} & Record<string, string>;

export interface ReportModalProps {
  isOpen: boolean;
  location: LatLng | null;
  onClose: () => void;
  onSubmit: (data: ReportFormData, photos: File[]) => Promise<void>;
}

/** Values must match the category enum in contracts/report_submitted.v1.json. */
export const REPORT_CATEGORIES = [
  { value: 'illegal_parking', label: 'Неправилно паркиране' },
  { value: 'littering', label: 'Замърсяване / отпадъци' },
  { value: 'illegal_dumping', label: 'Нерегламентирано сметище' },
  { value: 'broken_infrastructure', label: 'Повредена инфраструктура' },
  { value: 'street_lighting', label: 'Улично осветление' },
  { value: 'noise', label: 'Шум' },
  { value: 'damaged_greenery', label: 'Увредени зелени площи' },
  { value: 'abandoned_vehicle', label: 'Изоставен автомобил' },
] as const;

/** Categories where a licence plate helps the authority (hashed by the API, never stored). */
export const PLATE_CATEGORIES = new Set(['illegal_parking', 'abandoned_vehicle']);

export const MAX_PHOTOS = 5;
