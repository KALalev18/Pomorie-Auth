export interface ToastProps {
  message: string;
  tone?: 'warning' | 'success';
  visible: boolean;
  onDismiss: () => void;
}
