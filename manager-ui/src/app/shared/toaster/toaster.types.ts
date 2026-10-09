export type ToastSeverity = 'success' | 'info' | 'warning' | 'danger';

export interface ToastMessage {
  readonly severity: ToastSeverity;
  readonly summary: string;
  readonly detail?: string;
}

export const TOAST_DURATION_MS = 6000;

export const TOAST_ICON: Readonly<Record<ToastSeverity, string>> = {
  success: 'fa-solid fa-circle-check',
  info: 'fa-solid fa-circle-info',
  warning: 'fa-solid fa-triangle-exclamation',
  danger: 'fa-solid fa-circle-exclamation',
};
