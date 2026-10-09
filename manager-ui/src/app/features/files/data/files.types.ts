import type { Page } from '@core/http/api.types';

export type EntryKind = 'file' | 'folder' | 'link' | 'other';

export interface Entry {
  readonly name: string;
  readonly path: string;
  readonly kind: EntryKind;
  readonly size: number;
  readonly modified: string;
  readonly mode: string;
}

export interface Listing extends Page<Entry> {
  readonly path: string;
  readonly parent: string | null;
  readonly root: string;
  readonly roots: readonly string[];
}

export interface ListingQuery {
  readonly server: string;
  readonly path: string | null;
  readonly page: number;
  readonly page_size: number;
}

export type UploadEvent =
  | { readonly kind: 'progress'; readonly sent: number; readonly total: number }
  | { readonly kind: 'uploaded'; readonly entry: Entry };

export interface NewFolder {
  readonly path: string;
  readonly name: string;
}

export interface Crumb {
  readonly path: string;
  readonly name: string;
}

export function trailOf(root: string, folder: string): readonly Crumb[] {
  const trail: Crumb[] = [{ path: root, name: root }];
  if (!isInside(folder, root) || folder === root) {
    return trail;
  }
  let path = root.endsWith('/') ? root.slice(0, -1) : root;
  for (const name of folder.slice(path.length + 1).split('/').filter((step) => step !== '')) {
    path = `${path}/${name}`;
    trail.push({ path, name });
  }
  return trail;
}

export function rootOf(path: string, roots: readonly string[]): string | null {
  const holding = roots.filter((root) => isInside(path, root));
  return holding.reduce<string | null>((deepest, root) => (deepest === null || root.length > deepest.length ? root : deepest), null);
}

function isInside(path: string, root: string): boolean {
  if (path === root) {
    return true;
  }
  return path.startsWith(root.endsWith('/') ? root : `${root}/`);
}

export type FolderNameProblem = 'required' | 'separator' | 'reserved';

export function folderNameProblem(name: string): FolderNameProblem | null {
  const trimmed = name.trim();
  if (trimmed === '') {
    return 'required';
  }
  if (/[/\\]/.test(trimmed)) {
    return 'separator';
  }
  if (trimmed === '.' || trimmed === '..') {
    return 'reserved';
  }
  return null;
}
