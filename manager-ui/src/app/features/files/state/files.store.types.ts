import type { Listing } from '../data/files.types';

export interface Upload {
  readonly server: string;
  readonly folder: string;
  readonly name: string;
  readonly sent: number;
  readonly total: number;
}

export interface ShownSource {
  readonly place: string | null;
  readonly listing: Listing | undefined;
}

export interface KnownRootsSource {
  readonly server: string | null;
  readonly roots: readonly string[] | undefined;
}
