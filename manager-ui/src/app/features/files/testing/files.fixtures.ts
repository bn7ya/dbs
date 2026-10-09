import type { Entry, Listing } from '../data/files.types';

export const SERVER_ID = '0f3c2b9e-1111-4c4f-9a43-7b1d2f0c0001';

export const ROOT = '/srv/app/media';
export const OTHER_ROOT = '/var/log/app';
export const ROOTS: readonly string[] = [ROOT, OTHER_ROOT];

export const FOLDER: Entry = {
  name: 'photos',
  path: `${ROOT}/photos`,
  kind: 'folder',
  size: 4096,
  modified: '2026-09-30T12:00:00Z',
  mode: 'drwxr-xr-x',
};

export const FILE: Entry = {
  name: 'report 2026+final.pdf',
  path: `${ROOT}/report 2026+final.pdf`,
  kind: 'file',
  size: 1_200_000,
  modified: '2026-09-29T08:30:00Z',
  mode: '-rw-r--r--',
};

export const LINK: Entry = {
  name: 'current',
  path: `${ROOT}/current`,
  kind: 'link',
  size: 11,
  modified: '2026-09-28T08:30:00Z',
  mode: 'lrwxrwxrwx',
};

export const OTHER: Entry = {
  name: 'app.sock',
  path: `${ROOT}/app.sock`,
  kind: 'other',
  size: 0,
  modified: '2026-09-28T08:30:00Z',
  mode: 'srwxrwxrwx',
};

export const NESTED: Entry = {
  name: 'cat.jpg',
  path: `${ROOT}/photos/cat.jpg`,
  kind: 'file',
  size: 512,
  modified: '2026-09-27T08:30:00Z',
  mode: '-rw-r--r--',
};

export function listingOf(
  results: readonly Entry[],
  { path = ROOT, count = results.length, roots = ROOTS }: { path?: string; count?: number; roots?: readonly string[] } = {},
): Listing {
  const root = roots.find((each) => path === each || path.startsWith(`${each}/`)) ?? path;
  const parent = path === root ? null : path.slice(0, path.lastIndexOf('/'));
  return { count, next: null, previous: null, results, path, parent, root, roots };
}
