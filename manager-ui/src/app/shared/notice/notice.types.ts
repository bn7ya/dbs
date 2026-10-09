export type NoticeSeverity = 'info' | 'success' | 'warning' | 'danger';

export const NOTICE_ICON: Readonly<Record<NoticeSeverity, string>> = {
  info: 'fa-solid fa-circle-info',
  success: 'fa-solid fa-circle-check',
  warning: 'fa-solid fa-triangle-exclamation',
  danger: 'fa-solid fa-circle-exclamation',
};
