import {
  DEPLOY_TIMEOUT_DEFAULT,
  branchProblem,
  gitNameProblem,
  requirementsProblem,
  servicesProblem,
  takesServices,
  timeoutProblem,
  unitProblem,
} from '../../data/deploy-catalogue';
import type { DeployStep, DeployStepKind, DeployStepOptions } from '../../data/redeploy.types';
import type { DraftProblems, DraftStep } from './step-drafts.types';

export const NO_PROBLEMS: DraftProblems = {
  remote: null,
  branch: null,
  services: null,
  unit: null,
  requirements: null,
  timeout: null,
};

export function emptyDraft(kind: DeployStepKind, key: number): DraftStep {
  return {
    key,
    kind,
    remote: '',
    branch: '',
    services: [],
    pull: false,
    unit: '',
    requirements: kind === 'pip_install' ? 'requirements.txt' : '',
    timeout: DEPLOY_TIMEOUT_DEFAULT,
  };
}

export function draftOf(step: DeployStep, key: number): DraftStep {
  const options = step.options;
  return {
    key,
    kind: step.kind,
    remote: options.remote ?? '',
    branch: options.branch ?? '',
    services: options.services ?? [],
    pull: options.pull ?? false,
    unit: options.unit ?? '',
    requirements: options.requirements ?? '',
    timeout: step.timeout_minutes,
  };
}

export function stepOf(draft: DraftStep): DeployStep {
  return { kind: draft.kind, options: optionsOf(draft), timeout_minutes: draft.timeout ?? DEPLOY_TIMEOUT_DEFAULT };
}

export function draftProblems(draft: DraftStep): DraftProblems {
  const pulling = draft.kind === 'git_pull';
  return {
    remote: pulling ? gitNameProblem(draft.remote.trim()) : null,
    branch: pulling ? branchProblem(draft.remote.trim(), draft.branch.trim()) : null,
    services: takesServices(draft.kind) ? servicesProblem(draft.services) : null,
    unit: draft.kind === 'systemd_user_restart' ? unitProblem(draft.unit.trim()) : null,
    requirements: draft.kind === 'pip_install' ? requirementsProblem(draft.requirements.trim()) : null,
    timeout: timeoutProblem(draft.timeout),
  };
}

export function hasProblems(problems: DraftProblems): boolean {
  return Object.values(problems).some((problem) => problem !== null);
}

function optionsOf(draft: DraftStep): DeployStepOptions {
  switch (draft.kind) {
    case 'git_pull': {
      const remote = draft.remote.trim();
      const branch = draft.branch.trim();
      return { ...(remote === '' ? {} : { remote }), ...(branch === '' ? {} : { branch }) };
    }
    case 'compose_pull':
    case 'compose_up':
      return { services: draft.services };
    case 'compose_build':
      return { services: draft.services, pull: draft.pull };
    case 'systemd_user_restart':
      return { unit: draft.unit.trim() };
    case 'pip_install':
      return { requirements: draft.requirements.trim() };
    default:
      return {};
  }
}
