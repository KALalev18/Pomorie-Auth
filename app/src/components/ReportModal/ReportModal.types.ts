import type { LatLng } from '../MapView/MapView.types';

export type ReportFormData = {
  category: string;
  description: string;
  contactEmail: string;
} & Record<string, string>;

export interface ReportModalProps {
  isOpen: boolean;
  location: LatLng | null;
  onClose: () => void;
  onSubmit: (data: ReportFormData) => void;
}

export const REPORT_CATEGORIES = [
  'Инфраструктура',
  'Улично осветление',
  'Чистота и отпадъци',
  'Зелени площи',
  'Водоснабдяване',
  'Безопасност',
  'Друго',
] as const;
