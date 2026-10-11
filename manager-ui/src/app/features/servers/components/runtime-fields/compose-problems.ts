import type { ComposeField, ComposeTarget } from './runtime-fields.types';

const SERVICE_NAME = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
const COMPOSE_FILE = /^(?!-)(?!(.*\/)?\.\.(\/|$))[^\0\r\n]+$/;

export function composeProblems(target: ComposeTarget): ReadonlyMap<ComposeField, string> {
  const problems = new Map<ComposeField, string>();
  if (target.runtime !== 'compose') {
    return problems;
  }
  const service = target.compose_service.trim();
  if (service === '') {
    problems.set('compose_service', 'compose_service_required');
  } else if (!SERVICE_NAME.test(service)) {
    problems.set('compose_service', 'invalid');
  }
  if (target.project_dir.trim() === '') {
    problems.set('project_dir', 'compose_folder_required');
  }
  if (target.compose_files.some((file) => !COMPOSE_FILE.test(file.trim()))) {
    problems.set('compose_files', 'invalid');
  }
  return problems;
}
