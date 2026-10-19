import type { BackupFile, UnfinishedJob } from '../data/backups.types';
import type { BackupPlan } from '../data/plans.types';

export interface Opening {
  readonly files?: readonly BackupFile[];
  readonly running?: readonly UnfinishedJob[];
  readonly queued?: readonly UnfinishedJob[];
}

export interface PlansOpening {
  readonly plans?: readonly BackupPlan[];
  readonly running?: readonly UnfinishedJob[];
  readonly queued?: readonly UnfinishedJob[];
}
