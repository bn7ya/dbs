export interface ConfirmOptions {
  readonly title: string;
  readonly message: string;
  readonly detail?: string;
  readonly acceptLabel: string;
  readonly rejectLabel: string;
  readonly acceptSeverity?: 'primary' | 'danger';
}
