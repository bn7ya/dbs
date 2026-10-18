import type { Listing } from '../data/files.types';

export interface Upload {
  readonly application: string;
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
  readonly application: string | null;
  readonly roots: readonly string[] | undefined;
}
