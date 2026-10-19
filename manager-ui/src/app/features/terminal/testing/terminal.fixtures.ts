import type {
  Terminal,
  TerminalApplication,
  TerminalOutputAnswer,
  TerminalServer,
} from '../data/terminals.types';

export const SERVER_ID = '5f0c6a52-6a59-4c55-9d0e-2b1f0a7c1e11';
export const APPLICATION_ID = '9b2d4e61-1c3f-4a8e-b7d2-6e5f4a3b2c10';

export const SERVER: TerminalServer = {
  id: SERVER_ID,
  name: 'web-1',
  host: '10.0.0.5',
  username: 'deploy',
};

export const APPLICATION: TerminalApplication = {
  id: APPLICATION_ID,
  name: 'shop',
  kind: 'compose',
  compose_service: 'web',
  container_name: '',
  project_dir: '/srv/shop',
};

export const TERMINAL: Terminal = {
  id: 'Zq1-terminal-one',
  mode: 'server',
  server: SERVER_ID,
  application: '',
  label: 'web-1',
  container: '',
  cols: 80,
  rows: 24,
  closed: false,
};

export const APPLICATION_TERMINAL: Terminal = {
  id: 'Zq2-terminal-two',
  mode: 'application',
  server: SERVER_ID,
  application: APPLICATION_ID,
  label: 'shop',
  container: 'web',
  cols: 80,
  rows: 24,
  closed: false,
};

export function base64Of(text: string): string {
  return btoa(String.fromCharCode(...new TextEncoder().encode(text)));
}

export function outputOf(text: string, cursor: number, rest: Partial<TerminalOutputAnswer> = {}): TerminalOutputAnswer {
  return {
    data: base64Of(text),
    cursor,
    skipped: false,
    closed: false,
    reason: '',
    exit_status: null,
    ...rest,
  };
}
