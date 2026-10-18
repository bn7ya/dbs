import { describe, expect, it } from 'vitest';

import {
  DEPLOY_STEP_KINDS,
  branchProblem,
  fitProblems,
  gitNameProblem,
  isStepProblem,
  kindsFor,
  requirementsProblem,
  servicesProblem,
  timeoutProblem,
  unitProblem,
} from './deploy-catalogue';

describe('the deploy step catalogue', () => {
  it('offers the Compose steps and a restart only to an application in a Compose service', () => {
    expect(kindsFor({ kind: 'compose', project_dir: '/srv/shop' })).toEqual([
      'git_pull',
      'compose_pull',
      'compose_build',
      'compose_up',
      'restart',
      'systemd_user_restart',
      'migrate',
      'collectstatic',
    ]);
  });

  it('offers a restart but no Compose step to an application in a container', () => {
    expect(kindsFor({ kind: 'container', project_dir: '/srv/shop' })).toEqual([
      'git_pull',
      'restart',
      'systemd_user_restart',
      'migrate',
      'collectstatic',
    ]);
  });

  it('offers pip install only on the server itself, and neither it nor git pull without a folder', () => {
    expect(kindsFor({ kind: 'host', project_dir: '/srv/shop' })).toEqual([
      'git_pull',
      'systemd_user_restart',
      'pip_install',
      'migrate',
      'collectstatic',
    ]);
    expect(kindsFor({ kind: 'host', project_dir: '' })).toEqual(['systemd_user_restart', 'migrate', 'collectstatic']);
  });

  it('names why a step does not fit, with the codes the manager uses', () => {
    expect(fitProblems('pip_install', { kind: 'compose', project_dir: '' })).toEqual([
      'project_dir_required',
      'host_required',
    ]);
    expect(fitProblems('compose_up', { kind: 'container', project_dir: '/srv' })).toEqual(['compose_required']);
    expect(fitProblems('restart', { kind: 'host', project_dir: '/srv' })).toEqual(['container_required']);
    expect(DEPLOY_STEP_KINDS.every((kind) => isStepProblem(fitProblems(kind, { kind: 'host', project_dir: '' })[0] ?? 'invalid_name'))).toBe(true);
  });

  it('takes an empty remote and branch, a branch alone, or both, but never a remote alone', () => {
    expect(branchProblem('', '')).toBeNull();
    expect(branchProblem('', 'main')).toBeNull();
    expect(branchProblem('origin', 'release/2026.10')).toBeNull();
    expect(branchProblem('origin', '')).toBe('branch_required');
    expect(gitNameProblem('-delete')).toBe('invalid_name');
    expect(gitNameProblem('my remote')).toBe('invalid_name');
    expect(branchProblem('origin', 'x;rm')).toBe('invalid_name');
  });

  it('checks Compose service names, at most twenty of them', () => {
    expect(servicesProblem([])).toBeNull();
    expect(servicesProblem(['web', 'worker_1', 'api.v2'])).toBeNull();
    expect(servicesProblem(['web server'])).toBe('invalid_service');
    expect(servicesProblem(['-web'])).toBe('invalid_service');
    expect(servicesProblem(Array.from({ length: 21 }, (_, index) => `s${index}`))).toBe('invalid_service');
  });

  it('asks for a user unit that ends in .service', () => {
    expect(unitProblem('app.service')).toBeNull();
    expect(unitProblem('app@1.service')).toBeNull();
    expect(unitProblem('app')).toBe('invalid_unit');
    expect(unitProblem('')).toBe('invalid_unit');
  });

  it('asks for a requirements file inside the folder', () => {
    expect(requirementsProblem('requirements.txt')).toBeNull();
    expect(requirementsProblem('requirements/prod.txt')).toBeNull();
    expect(requirementsProblem('/etc/passwd')).toBe('invalid_requirements');
    expect(requirementsProblem('../other/requirements.txt')).toBe('invalid_requirements');
    expect(requirementsProblem('-r')).toBe('invalid_requirements');
    expect(requirementsProblem('')).toBe('invalid_requirements');
  });

  it('allows a whole number of minutes from 1 to 120', () => {
    expect(timeoutProblem(1)).toBeNull();
    expect(timeoutProblem(120)).toBeNull();
    expect(timeoutProblem(0)).toBe('invalid_timeout');
    expect(timeoutProblem(121)).toBe('invalid_timeout');
    expect(timeoutProblem(2.5)).toBe('invalid_timeout');
    expect(timeoutProblem(null)).toBe('invalid_timeout');
  });

  it('knows its own codes from any other', () => {
    expect(isStepProblem('too_many_steps')).toBe(true);
    expect(isStepProblem('host_required')).toBe(true);
    expect(isStepProblem('invalid')).toBe(false);
  });
});
