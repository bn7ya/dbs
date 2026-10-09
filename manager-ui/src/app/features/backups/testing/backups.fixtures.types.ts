import type { BackupFile, BackupPlan, UnfinishedJob } from '../data/backups.types';

export interface Opening {
  readonly files?: readonly BackupFile[];
  readonly plans?: readonly BackupPlan[];
  readonly running?: readonly UnfinishedJob[];
  readonly queued?: readonly UnfinishedJob[];
}
