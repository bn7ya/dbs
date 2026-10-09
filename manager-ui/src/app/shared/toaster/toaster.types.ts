export type ToastSeverity = 'success' | 'info' | 'warning' | 'danger';

export interface ToastMessage {
  readonly severity: ToastSeverity;
  readonly summary: string;
  readonly detail?: string;
}
