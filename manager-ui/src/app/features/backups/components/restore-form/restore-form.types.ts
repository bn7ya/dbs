import type { BackupFile } from '../../data/backups.types';

export interface RestoreFormData {
  readonly file: BackupFile;
}

export type Sending = 'rehearse' | 'restore';
