import type { ApiError } from '@core/http/api.types';
import { errorText } from '@core/i18n/error-text.pipe';
import type { LocaleStore } from '@core/i18n/locale.store';
import type { Job } from '@core/jobs/job.types';
import { isolated } from '@shared/isolated/isolated';
import type { ToastMessage, ToastSeverity } from '@shared/toaster/toaster.types';
import type { CollectCounts } from './backups.store.types';

export function toast(severity: ToastSeverity, summary: string, name?: string): ToastMessage {
  return name === undefined ? { severity, summary } : { severity, summary, detail: isolated(name) };
}

export function failureToast(locale: LocaleStore, error: ApiError | string, name?: string): ToastMessage {
  return toast('danger', errorText(locale, error), name);
}

// A toast has no field to mark, so a refusal about one field is said in that field's own words.
export function refusalToast(locale: LocaleStore, error: ApiError, name?: string): ToastMessage {
  return failureToast(locale, Object.values(error.fields ?? {})[0]?.[0] ?? error, name);
}

export function backedUpToast(locale: LocaleStore, job: Job, name?: string): ToastMessage {
  if (job.detail['outcome'] === 'kept_on_server') {
    return toast('warning', locale.translate('backups.take.keptOnServer'), name);
  }
  const collected = collectCountsOf(job);
  if (collected !== null) {
    return toast('success', collectedText(locale, collected), name);
  }
  if (job.detail['warning'] === 'files_changed') {
    return toast('warning', locale.translate('backups.take.warning.files_changed'), name);
  }
  const done = job.detail['resumed'] === true ? 'backups.take.resumed' : 'backups.take.done';
  return toast('success', locale.translate(done), name);
}

function collectCountsOf(job: Job): CollectCounts | null {
  const { collected, skipped } = job.detail;
  return typeof collected === 'number' && typeof skipped === 'number' ? { collected, skipped } : null;
}

function collectedText(locale: LocaleStore, { collected, skipped }: CollectCounts): string {
  if (collected === 0) {
    return locale.translate('backups.collect.nothingNew');
  }
  const lines = [locale.translate('backups.collect.collected', { count: collected })];
  if (skipped > 0) {
    lines.push(locale.translate('backups.collect.skipped', { count: skipped }));
  }
  return lines.join(' ');
}
