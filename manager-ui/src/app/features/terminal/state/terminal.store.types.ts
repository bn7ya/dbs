import type { ApiError } from '@core/http/api.types';
import type { TerminalMode, TerminalReason } from '../data/terminals.types';

export interface TerminalPlace {
  readonly mode: TerminalMode;
  readonly id: string;
}

export type TerminalWhere =
  | { readonly kind: 'server'; readonly name: string; readonly username: string }
  | { readonly kind: 'host'; readonly name: string; readonly folder: string }
  | { readonly kind: 'compose'; readonly name: string; readonly service: string }
  | { readonly kind: 'container'; readonly name: string; readonly container: string };

export interface TerminalEnd {
  readonly reason: TerminalReason | null;
  readonly exitStatus: number | null;
  readonly error: ApiError | null;
}

export type TerminalFeed = { readonly kind: 'reset' } | { readonly kind: 'data'; readonly bytes: Uint8Array };
