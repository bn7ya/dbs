import type { AuthMethod, Server } from '../../data/servers.types';

export interface ServerFormData {
  readonly server: Server;
}

export interface ServerDraft {
  readonly name: string;
  readonly host: string;
  readonly port: number | null;
  readonly username: string;
  readonly auth_method: AuthMethod;
  readonly private_key: string;
  readonly key_passphrase: string;
  readonly password: string;
}

export type ServerDraftField = keyof ServerDraft;

export interface AuthMethodOption {
  readonly value: AuthMethod;
  readonly labelKey: string;
}
