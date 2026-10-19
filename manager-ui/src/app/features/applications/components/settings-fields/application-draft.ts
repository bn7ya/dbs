import type { Application, ApplicationSettings, Candidate } from '../../data/applications.types';
import { runtimeProblems } from '../runtime-fields/runtime-problems';
import type { ApplicationDraft, DraftField } from './settings-fields.types';

export const DEFAULT_PYTHON = 'python3';

export const DEFAULT_BACKUP_DIR = '/var/backups/dbs';

const ABSOLUTE_PATH = /^\/(?!.*(^|\/)\.\.(\/|$))/;

const SETTINGS_MODULE = /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$/;

export const BLANK_DRAFT: ApplicationDraft = {
  name: '',
  kind: 'host',
  engine: '',
  compose_project: '',
  compose_service: '',
  compose_files: [],
  container_name: '',
  project_dir: '',
  workdir: '',
  python_path: DEFAULT_PYTHON,
  manage_path: 'manage.py',
  settings_module: '',
  remote_backup_dir: DEFAULT_BACKUP_DIR,
  mounts: [],
  file_roots: [],
  env_path: '',
  env_location: 'host',
};

export const DETAIL_FIELDS: readonly DraftField[] = [
  'kind',
  'engine',
  'compose_project',
  'compose_service',
  'compose_files',
  'container_name',
  'project_dir',
  'workdir',
  'python_path',
  'manage_path',
  'settings_module',
  'remote_backup_dir',
  'mounts',
  'file_roots',
  'env_path',
  'env_location',
];

export function draftOf(application: Application): ApplicationDraft {
  return {
    name: application.name,
    kind: application.kind,
    engine: application.engine,
    compose_project: application.compose_project,
    compose_service: application.compose_service,
    compose_files: application.compose_files,
    container_name: application.container_name,
    project_dir: application.project_dir,
    workdir: application.workdir,
    python_path: application.python_path,
    manage_path: application.manage_path,
    settings_module: application.settings_module,
    remote_backup_dir: application.remote_backup_dir,
    mounts: application.mounts,
    file_roots: application.file_roots,
    env_path: application.env_path,
    env_location: application.env_location,
  };
}

export function draftFromCandidate(candidate: Candidate): ApplicationDraft {
  const env = candidate.env[0];
  return {
    name: nameOf(candidate),
    kind: candidate.kind,
    engine: candidate.engine,
    compose_project: candidate.compose_project,
    compose_service: candidate.compose_service,
    compose_files: candidate.compose_files,
    container_name: candidate.container_name,
    project_dir: candidate.project_dir,
    workdir: candidate.workdir,
    python_path: candidate.python_path || DEFAULT_PYTHON,
    manage_path: candidate.manage_path,
    settings_module: candidate.settings_module,
    remote_backup_dir: candidate.remote_backup_dir || DEFAULT_BACKUP_DIR,
    mounts: candidate.mounts,
    file_roots: candidate.file_roots.map((root) => root.path),
    env_path: env?.path ?? '',
    env_location: env?.location ?? 'host',
  };
}

export function draftFromFolder(folder: string): ApplicationDraft {
  return { ...BLANK_DRAFT, name: lastPart(folder), project_dir: folder };
}

export function settingsOf(draft: ApplicationDraft): ApplicationSettings {
  const contained = draft.kind !== 'host';
  return {
    name: draft.name.trim(),
    kind: draft.kind,
    engine: contained ? draft.engine : '',
    compose_project: draft.kind === 'compose' ? draft.compose_project.trim() : '',
    compose_service: draft.kind === 'compose' ? draft.compose_service.trim() : '',
    compose_files: draft.kind === 'compose' ? draft.compose_files.map((file) => file.trim()) : [],
    container_name: draft.kind === 'container' ? draft.container_name.trim() : '',
    project_dir: draft.project_dir.trim(),
    workdir: contained ? draft.workdir.trim() : '',
    python_path: draft.python_path.trim(),
    manage_path: draft.manage_path.trim(),
    settings_module: draft.settings_module.trim(),
    remote_backup_dir: draft.remote_backup_dir.trim(),
    mounts: draft.mounts,
    file_roots: draft.file_roots.map((root) => root.trim()),
    env_path: draft.env_path.trim(),
    env_location: contained ? draft.env_location : 'host',
  };
}

export function changedSettings(before: ApplicationDraft, after: ApplicationDraft): Partial<ApplicationSettings> {
  const was = settingsOf(before);
  const now = settingsOf(after);
  const fields = Object.keys(now) as (keyof ApplicationSettings)[];
  return Object.fromEntries(
    fields.filter((field) => JSON.stringify(was[field]) !== JSON.stringify(now[field])).map((field) => [field, now[field]]),
  );
}

export function draftProblems(draft: ApplicationDraft): ReadonlyMap<DraftField, string> {
  const problems = new Map<DraftField, string>(runtimeProblems(draft));
  for (const field of ['name', 'python_path', 'manage_path', 'remote_backup_dir'] as const) {
    if (draft[field].trim() === '') {
      problems.set(field, 'required');
    }
  }
  for (const field of ['project_dir', 'remote_backup_dir', 'env_path'] as const) {
    const path = draft[field].trim();
    if (path !== '' && !ABSOLUTE_PATH.test(path)) {
      problems.set(field, 'absolute_path_required');
    }
  }
  const workdir = draft.workdir.trim();
  if (draft.kind !== 'host' && workdir !== '' && !ABSOLUTE_PATH.test(workdir)) {
    problems.set('workdir', 'absolute_path_required');
  }
  const settings = draft.settings_module.trim();
  if (settings !== '' && !SETTINGS_MODULE.test(settings)) {
    problems.set('settings_module', 'invalid');
  }
  if (draft.file_roots.some((root) => !ABSOLUTE_PATH.test(root.trim()))) {
    problems.set('file_roots', 'absolute_path_required');
  }
  return problems;
}

function nameOf(candidate: Candidate): string {
  return candidate.compose_project || candidate.compose_service || candidate.container_name || lastPart(candidate.project_dir);
}

function lastPart(path: string): string {
  return path.split('/').filter((part) => part !== '').at(-1) ?? '';
}
