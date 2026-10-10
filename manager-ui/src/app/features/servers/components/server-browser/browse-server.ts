import type { Dialogs } from '@shared/dialogs/dialogs';
import { ServerBrowser } from './server-browser';
import type { BrowsedField, BrowsedPaths, ServerBrowserData } from './server-browser.types';

const ABSOLUTE_PATH = /^\//;

const TITLES: Readonly<Record<BrowsedField, string>> = {
  project_dir: 'servers.browser.title.project',
  remote_backup_dir: 'servers.browser.title.backups',
  env_path: 'servers.browser.title.env',
  file_roots: 'servers.browser.title.folder',
};

export function browseServer(
  dialogs: Dialogs,
  serverId: string,
  field: BrowsedField,
  paths: BrowsedPaths,
  projects: readonly string[] = [],
): Promise<string | undefined> {
  return dialogs
    .open<string, ServerBrowserData>(ServerBrowser, {
      titleKey: TITLES[field],
      data: {
        serverId,
        start: startOf(field, paths),
        mode: field === 'env_path' ? 'file' : 'folder',
        projects: field === 'project_dir' ? projects : [],
      },
      size: 'lg',
    })
    .whenClosed();
}

function startOf(field: BrowsedField, paths: BrowsedPaths): string | null {
  const project = paths.project_dir.trim();
  const start =
    field === 'project_dir' || field === 'file_roots' ? project : parentOf(paths[field].trim()) || project;
  return ABSOLUTE_PATH.test(start) ? start : null;
}

function parentOf(path: string): string {
  const cut = path.replace(/\/+$/, '').lastIndexOf('/');
  return cut > 0 ? path.slice(0, cut) : cut === 0 ? '/' : '';
}
