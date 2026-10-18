import type { TerminalSize } from '@shared/terminal-view/terminal-view.types';

export type TerminalMode = 'server' | 'application';

export type TerminalReason =
  | 'exited'
  | 'closed'
  | 'idle'
  | 'unpolled'
  | 'lifetime'
  | 'revoked'
  | 'signed_out'
  | 'lost'
  | 'stopped';

export interface Terminal {
  readonly id: string;
  readonly mode: TerminalMode;
  readonly server: string;
  readonly application: string;
  readonly label: string;
  readonly container: string;
  readonly cols: number;
  readonly rows: number;
  readonly closed: boolean;
}

export interface TerminalList {
  readonly results: readonly Terminal[];
}

export interface TerminalOpening extends TerminalSize {
  readonly mode: TerminalMode;
  readonly server?: string;
  readonly application?: string;
  readonly password: string;
}

export interface TerminalOutputAnswer {
  readonly data: string;
  readonly cursor: number;
  readonly skipped: boolean;
  readonly closed: boolean;
  readonly reason: TerminalReason | '';
  readonly exit_status: number | null;
}

export interface TerminalOutput {
  readonly bytes: Uint8Array;
  readonly cursor: number;
  readonly skipped: boolean;
  readonly closed: boolean;
  readonly reason: TerminalReason | null;
  readonly exitStatus: number | null;
}

export interface TerminalInputAnswer {
  readonly accepted: boolean;
}

export interface TerminalServer {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly username: string;
}

export type ApplicationKind = 'host' | 'compose' | 'container';

export interface TerminalApplication {
  readonly id: string;
  readonly name: string;
  readonly kind: ApplicationKind;
  readonly compose_service: string;
  readonly container_name: string;
  readonly project_dir: string;
}

export const TERMINAL_COLS = { min: 20, max: 500 } as const;
export const TERMINAL_ROWS = { min: 5, max: 200 } as const;
export const TERMINAL_INPUT_MAX_BYTES = 64 * 1024;
