import type { ConnectionSnippet, SnippetHostKey, SnippetParse } from './connection-snippet.types';

const NOTHING: SnippetParse = { snippet: null, error: null };

export function parseSnippet(text: string): SnippetParse {
  if (text.trim() === '') {
    return NOTHING;
  }
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    return { snippet: null, error: 'snippet_invalid' };
  }
  if (!isRecord(value) || !('dbs_connection' in value)) {
    return { snippet: null, error: 'snippet_not_dbs' };
  }
  return { snippet: snippetOf(value), error: null };
}

export function versionBelow(version: string, floor: string): boolean {
  const parts = (text: string): number[] => text.split(/[.+-]/).slice(0, 3).map((part) => Number.parseInt(part, 10) || 0);
  const [have, need] = [parts(version), parts(floor)];
  for (let index = 0; index < 3; index += 1) {
    if ((have[index] ?? 0) !== (need[index] ?? 0)) {
      return (have[index] ?? 0) < (need[index] ?? 0);
    }
  }
  return false;
}

function snippetOf(value: Readonly<Record<string, unknown>>): ConnectionSnippet {
  const text = (key: string): string => (typeof value[key] === 'string' ? value[key] : '');
  const roots = Array.isArray(value['file_roots']) ? value['file_roots'] : [];
  const keys = Array.isArray(value['host_keys']) ? value['host_keys'] : [];
  return {
    hostname: text('hostname'),
    ssh_user: text('ssh_user'),
    project_dir: text('project_dir'),
    python_path: text('python_path'),
    manage_path: text('manage_path'),
    settings_module: text('settings_module'),
    remote_backup_dir: text('remote_backup_dir'),
    file_roots: roots.filter((root): root is string => typeof root === 'string'),
    env_path: text('env_path'),
    dbs_version: text('dbs_version'),
    host_keys: keys.filter(isHostKey),
  };
}

function isRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isHostKey(value: unknown): value is SnippetHostKey {
  return isRecord(value) && typeof value['type'] === 'string' && typeof value['fingerprint'] === 'string';
}
