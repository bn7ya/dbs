import type { CheckProblem, DeploymentProfile, DeploymentQuestion, DiscoveryProblem } from './applications.types';
import type { NextStep, QuestionDefinition, StepPlace } from './deployment.types';

export const DEPLOYMENT_QUESTIONS: readonly QuestionDefinition[] = [
  { key: 'runs_in', options: ['host', 'compose', 'container'] },
  { key: 'engine', options: ['docker', 'podman'] },
  { key: 'database', options: ['postgresql', 'mysql', 'mariadb', 'sqlite', 'other'] },
  { key: 'database_runs', options: ['compose', 'this_server', 'elsewhere', 'file'] },
  { key: 'settings_from', options: ['folder_env', 'compose_env_file', 'image', 'environment'] },
  { key: 'source', options: ['git', 'copied', 'image'] },
  { key: 'process_manager', options: ['systemd', 'systemd_user', 'supervisor', 'other'] },
  { key: 'web_server', options: ['nginx', 'other', 'none'] },
];

const HOST_ONLY: ReadonlySet<DeploymentQuestion> = new Set(['process_manager', 'web_server']);

export function asks(question: DeploymentQuestion, profile: DeploymentProfile): boolean {
  if (question === 'engine') {
    return profile.runs_in !== 'host';
  }
  if (HOST_ONLY.has(question)) {
    return profile.runs_in === undefined || profile.runs_in === 'host';
  }
  return true;
}

export function answerOf(profile: DeploymentProfile | null | undefined, question: DeploymentQuestion): string {
  return profile?.[question] ?? '';
}

export function withAnswer(profile: DeploymentProfile, question: DeploymentQuestion, value: string): DeploymentProfile {
  const answers = new Map<string, string>(Object.entries(profile).filter((entry): entry is [string, string] => !!entry[1]));
  if (value) {
    answers.set(question, value);
  } else {
    answers.delete(question);
  }
  return Object.fromEntries(answers);
}

export function asked(profile: DeploymentProfile): DeploymentProfile {
  return DEPLOYMENT_QUESTIONS.reduce<DeploymentProfile>(
    (kept, question) => (asks(question.key, profile) ? withAnswer(kept, question.key, answerOf(profile, question.key)) : kept),
    {},
  );
}

export function merged(said: DeploymentProfile, found: DeploymentProfile | undefined): DeploymentProfile {
  return DEPLOYMENT_QUESTIONS.reduce<DeploymentProfile>(
    (kept, question) => withAnswer(kept, question.key, answerOf(found, question.key) || answerOf(said, question.key)),
    {},
  );
}

export function answerKey(question: DeploymentQuestion, value: string): string {
  return value ? `applications.deployment.${question}.${value}` : 'applications.deployment.notSure';
}

export function nextSteps(problems: readonly (CheckProblem | DiscoveryProblem)[], place: StepPlace): NextStep[] {
  return problems.map((problem) => stepFor(problem, place)).filter((step): step is NextStep => step !== null);
}

function stepFor(problem: CheckProblem | DiscoveryProblem, place: StepPlace): NextStep | null {
  const engine = place.engine || 'docker';
  const compose = place.kind === 'compose';
  const host = place.kind === 'host';
  const service = place.compose_service;
  const rebuild = compose ? `${engine} compose build ${service} && ${engine} compose up -d ${service}` : '';
  const step = (variant: string, command = '', values: Record<string, string> = {}): NextStep => ({
    key: `applications.nextSteps.${problem}${variant ? `.${variant}` : ''}`,
    values,
    command,
  });
  switch (problem) {
    case 'engine_permission_denied':
      return engine === 'docker' ? step('docker', 'sudo usermod -aG docker "$USER"') : step('podman');
    case 'engine_missing':
      return step('');
    case 'container_not_running':
      return compose
        ? step('compose', `${engine} compose up -d ${service}`, { service })
        : step('container', `${engine} start ${place.container_name}`, { container: place.container_name });
    case 'dbs_missing':
      return host
        ? step('host', `${place.python_path} -m pip install django-dbs`)
        : step('image', rebuild, { service });
    case 'dbs_too_old':
      return host
        ? step('host', `${place.python_path} -m pip install --upgrade django-dbs`)
        : step('image', rebuild, { service });
    case 'backup_command_missing':
      return step('', host ? `${place.python_path} manage.py dbs upgrade` : '');
    case 'env_file_missing':
      return step('', '', { path: place.env_path ?? '' });
    case 'root_missing':
      return step('');
    case 'backup_dir_not_mounted':
      return compose
        ? step('compose', `- ./backups:${place.remote_backup_dir}`, { dir: place.remote_backup_dir, service })
        : step('container', '', { dir: place.remote_backup_dir });
    case 'backup_dir_missing':
      return step('', `mkdir -p ${place.remote_backup_dir}`, { dir: place.remote_backup_dir });
  }
}
