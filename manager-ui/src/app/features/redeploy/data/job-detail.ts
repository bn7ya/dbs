import type { StepStatus } from '@shared/steps-list/steps-list.types';
import type { DeployOutcome, JobDetail as Detail, JobStep, MoveOutcome, Revisions } from './redeploy.types';

const STEP_STATUSES: ReadonlySet<string> = new Set<StepStatus>(['pending', 'running', 'succeeded', 'failed', 'skipped']);

export function jobStepsOf(detail: Detail): readonly JobStep[] {
  const steps = detail['steps'];
  if (!Array.isArray(steps)) {
    return [];
  }
  return steps.filter(isJobStep);
}

export function failedStepOf(detail: Detail): string | null {
  const failed = detail['failed_step'];
  return typeof failed === 'string' ? failed : null;
}

export function isRehearsal(detail: Detail): boolean {
  return detail['rehearsal'] === true;
}

export function moveOutcomeOf(detail: Detail): MoveOutcome {
  const target = detail['target_application'];
  return {
    target: typeof target === 'string' ? target : null,
    revertable: detail['revertable'] === true,
    usedChosenBackup: detail['fresh_backup'] === false,
    sourceSilent: detail['source_reachable'] === false,
  };
}

export function deployOutcomeOf(detail: Detail): DeployOutcome {
  return {
    revertable: detail['revertable'] === true,
    before: revisionsOf(detail['before']),
    after: revisionsOf(detail['after']),
  };
}

function revisionsOf(value: unknown): Revisions {
  if (typeof value !== 'object' || value === null) {
    return {};
  }
  const found = value as Record<string, unknown>;
  return {
    ...(typeof found['git_head'] === 'string' ? { git_head: found['git_head'] } : {}),
    ...(typeof found['image'] === 'string' ? { image: found['image'] } : {}),
  };
}

function isJobStep(value: unknown): value is JobStep {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const step = value as Record<string, unknown>;
  return (
    typeof step['step'] === 'string' &&
    typeof step['status'] === 'string' &&
    STEP_STATUSES.has(step['status']) &&
    (step['index'] === undefined || typeof step['index'] === 'number')
  );
}
