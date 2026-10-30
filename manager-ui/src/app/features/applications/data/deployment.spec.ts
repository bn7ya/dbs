import { describe, expect, it } from 'vitest';

import { APPLICATION, COMPOSE_CANDIDATE } from '../testing/applications.fixtures';
import { asked, asks, merged, nextSteps, withAnswer } from './deployment';

describe('deployment', () => {
  it('asks for the engine only for containers, and the process manager only on the server', () => {
    expect(asks('engine', { runs_in: 'host' })).toBe(false);
    expect(asks('engine', {})).toBe(true);
    expect(asks('process_manager', { runs_in: 'compose' })).toBe(false);
    expect(asks('web_server', {})).toBe(true);
  });

  it('drops a Not sure answer and keeps the others', () => {
    expect(withAnswer({ runs_in: 'host', database: 'sqlite' }, 'database', '')).toEqual({ runs_in: 'host' });
    expect(withAnswer({}, 'source', 'git')).toEqual({ source: 'git' });
  });

  it('forgets answers to questions that no longer apply', () => {
    expect(asked({ runs_in: 'compose', engine: 'docker', web_server: 'nginx' })).toEqual({
      runs_in: 'compose',
      engine: 'docker',
    });
  });

  it('takes what was found over what was said, and keeps what was not found', () => {
    expect(merged({ runs_in: 'compose', web_server: 'nginx' }, { runs_in: 'host', database: 'postgresql' })).toEqual({
      runs_in: 'host',
      database: 'postgresql',
      web_server: 'nginx',
    });
  });

  it('offers a command for each problem it knows how to fix', () => {
    const steps = nextSteps(['dbs_missing', 'container_not_running', 'backup_dir_not_mounted'], COMPOSE_CANDIDATE);

    expect(steps.map((step) => step.key)).toEqual([
      'applications.nextSteps.dbs_missing.image',
      'applications.nextSteps.container_not_running.compose',
      'applications.nextSteps.backup_dir_not_mounted.compose',
    ]);
    expect(steps[1].command).toBe(`docker compose up -d ${COMPOSE_CANDIDATE.compose_service}`);
  });

  it('installs django-dbs with the application’s own Python on the server', () => {
    const [step] = nextSteps(['dbs_missing'], { ...APPLICATION, kind: 'host', python_path: '/srv/shop/.venv/bin/python' });

    expect(step.command).toBe('/srv/shop/.venv/bin/python -m pip install django-dbs');
  });
});
