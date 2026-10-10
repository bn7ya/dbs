import type { RemoteFolder } from '../data/servers.types';

export interface BrowserShownSource {
  readonly place: string | null;
  readonly folder: RemoteFolder | undefined;
}

export interface BrowserCrumb {
  readonly path: string;
  readonly name: string;
}
