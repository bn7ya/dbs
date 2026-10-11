import { describe, expect, it } from 'vitest';

import { composeProblems } from './compose-problems';

const COMPOSE = { runtime: 'compose' as const, compose_service: 'backend', compose_files: [], project_dir: '/srv/shop' };

describe('composeProblems', () => {
  it('finds nothing to say about a project that runs on the host', () => {
    expect(composeProblems({ ...COMPOSE, runtime: 'host', compose_service: '', project_dir: '' }).size).toBe(0);
  });

  it('accepts a service, a folder and files inside it', () => {
    expect(composeProblems({ ...COMPOSE, compose_files: ['compose.yaml', 'deploy/compose.prod.yaml'] }).size).toBe(0);
  });

  it('names each missing or unusable value', () => {
    expect(Object.fromEntries(composeProblems({ ...COMPOSE, compose_service: '', project_dir: '' }))).toEqual({
      compose_service: 'compose_service_required',
      project_dir: 'compose_folder_required',
    });
    expect(composeProblems({ ...COMPOSE, compose_service: '-d' }).get('compose_service')).toBe('invalid');
    expect(composeProblems({ ...COMPOSE, compose_files: ['-p'] }).get('compose_files')).toBe('invalid');
    expect(composeProblems({ ...COMPOSE, compose_files: ['a/../b.yaml'] }).get('compose_files')).toBe('invalid');
  });
});
