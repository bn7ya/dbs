import { describe, expect, it } from 'vitest';

import { APPLICATION, COMPOSE_CANDIDATE, HOST_CANDIDATE } from '../../testing/applications.fixtures';
import { changedSettings, draftFromCandidate, draftFromFolder, draftOf, draftProblems, settingsOf } from './application-draft';

describe('application drafts', () => {
  it('fills a draft from what discovery found, its first .env first', () => {
    const draft = draftFromCandidate(COMPOSE_CANDIDATE);

    expect(draft).toMatchObject({
      name: 'shop',
      kind: 'compose',
      engine: 'docker',
      compose_service: 'web',
      project_dir: '/srv/shop',
      workdir: '/app',
      python_path: '/app/.venv/bin/python',
      settings_module: 'shop.settings',
      remote_backup_dir: '/var/backups/dbs',
      file_roots: ['/app/media'],
      env_path: '/srv/shop/.env',
      env_location: 'host',
    });
    expect(draft.mounts).toEqual(COMPOSE_CANDIDATE.mounts);
  });

  it('falls back to python3 and the default backup folder when discovery found neither', () => {
    const draft = draftFromCandidate({ ...HOST_CANDIDATE, python_path: '', env: [] });

    expect(draft).toMatchObject({ name: 'shop', python_path: 'python3', remote_backup_dir: '/var/backups/dbs', env_path: '' });
  });

  it('starts a draft by hand from the folder, named after it', () => {
    expect(draftFromFolder('/srv/blog/')).toMatchObject({ name: 'blog', kind: 'host', project_dir: '/srv/blog/' });
  });

  it('sends no container settings for an application on the host', () => {
    const settings = settingsOf({ ...draftOf(APPLICATION), kind: 'host', name: ' shop ' });

    expect(settings).toMatchObject({
      name: 'shop',
      kind: 'host',
      engine: '',
      compose_project: '',
      compose_service: '',
      workdir: '',
      env_location: 'host',
    });
  });

  it('names only the settings an edit changed', () => {
    const before = draftOf(APPLICATION);

    expect(changedSettings(before, before)).toEqual({});
    expect(changedSettings(before, { ...before, settings_module: 'shop.prod', file_roots: ['/app/media', '/app/static'] })).toEqual({
      settings_module: 'shop.prod',
      file_roots: ['/app/media', '/app/static'],
    });
  });

  it('names each value that cannot be saved', () => {
    const problems = draftProblems({
      ...draftOf(APPLICATION),
      name: ' ',
      project_dir: 'srv/shop',
      workdir: '../app',
      settings_module: 'shop-settings',
      file_roots: ['media'],
      compose_service: '',
    });

    expect(Object.fromEntries(problems)).toEqual({
      name: 'required',
      project_dir: 'absolute_path_required',
      workdir: 'absolute_path_required',
      settings_module: 'invalid',
      file_roots: 'absolute_path_required',
      compose_service: 'compose_service_required',
    });
    expect(draftProblems(draftOf(APPLICATION)).size).toBe(0);
  });
});
