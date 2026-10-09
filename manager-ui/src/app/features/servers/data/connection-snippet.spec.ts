import { describe, expect, it } from 'vitest';

import { parseSnippet, versionBelow } from './connection-snippet';

const SNIPPET = {
  dbs_connection: 1,
  hostname: 'web-1',
  ssh_user: 'deploy',
  project_dir: '/srv/app',
  python_path: '/srv/app/.venv/bin/python',
  manage_path: 'manage.py',
  settings_module: 'app.settings',
  remote_backup_dir: '/var/backups/dbs',
  file_roots: ['/srv/app/media', 7],
  env_path: '/srv/app/.env',
  dbs_version: '0.5.0',
  host_keys: [{ type: 'ssh-ed25519', fingerprint: 'SHA256:abc' }, { type: 'broken' }],
};

describe('parseSnippet', () => {
  it('reads nothing from nothing', () => {
    expect(parseSnippet('  ')).toEqual({ snippet: null, error: null });
  });

  it('names text that is not JSON, and JSON that is not a connection snippet', () => {
    expect(parseSnippet('{not json').error).toBe('snippet_invalid');
    expect(parseSnippet('[1, 2]').error).toBe('snippet_not_dbs');
    expect(parseSnippet('{"hostname": "web-1"}').error).toBe('snippet_not_dbs');
  });

  it('keeps the typed values and drops what does not fit', () => {
    const { snippet } = parseSnippet(JSON.stringify(SNIPPET));

    expect(snippet?.hostname).toBe('web-1');
    expect(snippet?.file_roots).toEqual(['/srv/app/media']);
    expect(snippet?.host_keys).toEqual([{ type: 'ssh-ed25519', fingerprint: 'SHA256:abc' }]);
  });
});

describe('versionBelow', () => {
  it('compares dotted versions part by part', () => {
    expect(versionBelow('0.4.9', '0.5.0')).toBe(true);
    expect(versionBelow('0.5.0', '0.5.0')).toBe(false);
    expect(versionBelow('0.10.0', '0.5.0')).toBe(false);
    expect(versionBelow('1.0', '0.5.0')).toBe(false);
  });
});
