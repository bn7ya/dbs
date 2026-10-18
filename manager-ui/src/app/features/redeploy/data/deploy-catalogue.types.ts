import type { DeployApplication } from './redeploy.types';

export type DeployPlace = Pick<DeployApplication, 'kind' | 'project_dir'>;

export type FitProblem = 'project_dir_required' | 'compose_required' | 'container_required' | 'host_required';

export type StepProblem =
  | FitProblem
  | 'unknown_step'
  | 'unknown_option'
  | 'invalid_name'
  | 'branch_required'
  | 'invalid_service'
  | 'invalid_unit'
  | 'invalid_requirements'
  | 'invalid_timeout'
  | 'too_many_steps';
