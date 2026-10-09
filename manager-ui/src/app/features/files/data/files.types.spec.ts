import { describe, expect, it } from 'vitest';

import { folderNameProblem, rootOf, trailOf } from './files.types';

describe('trailOf', () => {
  it('is the allowed folder alone at the allowed folder', () => {
    expect(trailOf('/srv/app/media', '/srv/app/media')).toEqual([{ path: '/srv/app/media', name: '/srv/app/media' }]);
  });

  it('steps down one folder name at a time below it', () => {
    expect(trailOf('/srv/app/media', '/srv/app/media/photos/2026')).toEqual([
      { path: '/srv/app/media', name: '/srv/app/media' },
      { path: '/srv/app/media/photos', name: 'photos' },
      { path: '/srv/app/media/photos/2026', name: '2026' },
    ]);
  });

  it('reads an allowed folder written with a closing slash, and the whole disk', () => {
    expect(trailOf('/srv/app/', '/srv/app/media').map((crumb) => crumb.path)).toEqual(['/srv/app/', '/srv/app/media']);
    expect(trailOf('/', '/etc/nginx').map((crumb) => crumb.name)).toEqual(['/', 'etc', 'nginx']);
  });

  it('never steps outside the allowed folder, even past a shared prefix', () => {
    expect(trailOf('/srv/app', '/srv/application/x')).toEqual([{ path: '/srv/app', name: '/srv/app' }]);
  });
});

describe('rootOf', () => {
  const roots = ['/srv/app', '/srv/app/media', '/var/log'];

  it('finds the deepest allowed folder a path is inside', () => {
    expect(rootOf('/srv/app/media/photos', roots)).toBe('/srv/app/media');
    expect(rootOf('/srv/app/static', roots)).toBe('/srv/app');
    expect(rootOf('/var/log', roots)).toBe('/var/log');
  });

  it('is null outside every one of them', () => {
    expect(rootOf('/srv/application', roots)).toBeNull();
    expect(rootOf('/etc', [])).toBeNull();
  });
});

describe('folderNameProblem', () => {
  it('takes an ordinary name, in any script, with its surrounding spaces ignored', () => {
    expect(folderNameProblem('photos')).toBeNull();
    expect(folderNameProblem('  صور 2026 ')).toBeNull();
    expect(folderNameProblem('.config')).toBeNull();
    expect(folderNameProblem('...')).toBeNull();
  });

  it('asks for a name when there is none', () => {
    expect(folderNameProblem('')).toBe('required');
    expect(folderNameProblem('   ')).toBe('required');
  });

  it('refuses a name with a path separator in it', () => {
    expect(folderNameProblem('a/b')).toBe('separator');
    expect(folderNameProblem('a\\b')).toBe('separator');
  });

  it('refuses the two names that already mean a folder', () => {
    expect(folderNameProblem('.')).toBe('reserved');
    expect(folderNameProblem(' .. ')).toBe('reserved');
  });
});
