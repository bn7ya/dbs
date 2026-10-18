import type { DeployPlace, FitProblem, StepProblem } from './deploy-catalogue.types';
import type { DeployStepKind } from './redeploy.types';

// The manager's own catalogue (`dbs/manager/redeploy/catalogue.py`); the backend checks it again on save.
export const DEPLOY_STEP_KINDS: readonly DeployStepKind[] = [
  'git_pull',
  'compose_pull',
  'compose_build',
  'compose_up',
  'restart',
  'systemd_user_restart',
  'pip_install',
  'migrate',
  'collectstatic',
];

export const DEPLOY_STEPS_MAX = 12;
export const DEPLOY_TIMEOUT_MIN = 1;
export const DEPLOY_TIMEOUT_MAX = 120;
export const DEPLOY_TIMEOUT_DEFAULT = 10;
export const DEPLOY_SERVICES_MAX = 20;

export const STEP_PROBLEMS: readonly StepProblem[] = [
  'unknown_step',
  'unknown_option',
  'invalid_name',
  'branch_required',
  'invalid_service',
  'invalid_unit',
  'invalid_requirements',
  'invalid_timeout',
  'too_many_steps',
  'project_dir_required',
  'compose_required',
  'container_required',
  'host_required',
];

const COMPOSE_KINDS: ReadonlySet<DeployStepKind> = new Set(['compose_pull', 'compose_build', 'compose_up']);
const FOLDER_KINDS: ReadonlySet<DeployStepKind> = new Set(['git_pull', 'pip_install']);

const GIT_NAME = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$/;
const SERVICE_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/;
const UNIT_NAME = /^[A-Za-z0-9][A-Za-z0-9@._-]{0,99}\.service$/;
const RELATIVE_FILE = /^(?!-)(?!\/)(?!(.*\/)?\.\.(\/|$))[A-Za-z0-9._/-]{1,200}$/;

export function takesServices(kind: DeployStepKind): boolean {
  return COMPOSE_KINDS.has(kind);
}

export function fitProblems(kind: DeployStepKind, place: DeployPlace): readonly FitProblem[] {
  const problems: FitProblem[] = [];
  if (FOLDER_KINDS.has(kind) && place.project_dir === '') {
    problems.push('project_dir_required');
  }
  if (COMPOSE_KINDS.has(kind) && place.kind !== 'compose') {
    problems.push('compose_required');
  }
  if (kind === 'restart' && place.kind === 'host') {
    problems.push('container_required');
  }
  if (kind === 'pip_install' && place.kind !== 'host') {
    problems.push('host_required');
  }
  return problems;
}

export function kindsFor(place: DeployPlace): readonly DeployStepKind[] {
  return DEPLOY_STEP_KINDS.filter((kind) => fitProblems(kind, place).length === 0);
}

export function gitNameProblem(name: string): StepProblem | null {
  return name === '' || GIT_NAME.test(name) ? null : 'invalid_name';
}

export function branchProblem(remote: string, branch: string): StepProblem | null {
  if (branch !== '') {
    return gitNameProblem(branch);
  }
  return remote === '' ? null : 'branch_required';
}

export function servicesProblem(services: readonly string[]): StepProblem | null {
  const valid = services.length <= DEPLOY_SERVICES_MAX && services.every((name) => SERVICE_NAME.test(name));
  return valid ? null : 'invalid_service';
}

export function unitProblem(unit: string): StepProblem | null {
  return UNIT_NAME.test(unit) ? null : 'invalid_unit';
}

export function requirementsProblem(file: string): StepProblem | null {
  return RELATIVE_FILE.test(file) ? null : 'invalid_requirements';
}

export function timeoutProblem(minutes: number | null): StepProblem | null {
  const valid =
    minutes !== null && Number.isInteger(minutes) && minutes >= DEPLOY_TIMEOUT_MIN && minutes <= DEPLOY_TIMEOUT_MAX;
  return valid ? null : 'invalid_timeout';
}

export function isStepProblem(code: string): code is StepProblem {
  return (STEP_PROBLEMS as readonly string[]).includes(code);
}
