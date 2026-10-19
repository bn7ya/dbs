import { describe, expect, it } from 'vitest';

import type { RuntimeTarget } from './runtime-fields.types';
import { runtimeProblems } from './runtime-problems';

const COMPOSE: RuntimeTarget = {
  kind: 'compose',
  engine: 'docker',
  compose_project: '',
  compose_service: 'backend',
  compose_files: [],
  container_name: '',
  project_dir: '/srv/shop',
};

describe('runtimeProblems', () => {
  it('finds nothing to say about an application that runs on the host', () => {
    expect(runtimeProblems({ ...COMPOSE, kind: 'host', engine: '', compose_service: '', project_dir: '' }).size).toBe(0);
  });

  it('accepts a service, a folder and files inside it', () => {
    expect(runtimeProblems({ ...COMPOSE, compose_files: ['compose.yaml', 'deploy/compose.prod.yaml'] }).size).toBe(0);
  });

  it('names each missing or unusable Compose value', () => {
    expect(Object.fromEntries(runtimeProblems({ ...COMPOSE, engine: '', compose_service: '', project_dir: '' }))).toEqual({
      engine: 'engine_required',
      compose_service: 'compose_service_required',
      project_dir: 'compose_folder_required',
    });
    expect(runtimeProblems({ ...COMPOSE, compose_service: '-d' }).get('compose_service')).toBe('invalid');
    expect(runtimeProblems({ ...COMPOSE, compose_project: 'shop prod' }).get('compose_project')).toBe('invalid');
    expect(runtimeProblems({ ...COMPOSE, compose_files: ['-p'] }).get('compose_files')).toBe('invalid');
    expect(runtimeProblems({ ...COMPOSE, compose_files: ['a/../b.yaml'] }).get('compose_files')).toBe('invalid');
  });

  it('wants a container name for a container, and no Compose folder', () => {
    const container: RuntimeTarget = { ...COMPOSE, kind: 'container', engine: 'podman', compose_service: '', project_dir: '' };

    expect(Object.fromEntries(runtimeProblems(container))).toEqual({ container_name: 'container_required' });
    expect(runtimeProblems({ ...container, container_name: 'shop-web-1' }).size).toBe(0);
    expect(runtimeProblems({ ...container, container_name: '--rm' }).get('container_name')).toBe('invalid');
  });
});
