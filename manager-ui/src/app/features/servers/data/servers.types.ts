import type { ConnectionState } from '@shared/connection-dot/connection-dot.types';

export type AuthMethod = 'key' | 'password';

export type CheckStatus = 'unknown' | 'ok' | 'problem' | 'failed';

export type ContainerEngine = 'docker' | 'podman';

export interface EngineReport {
  readonly installed: boolean;
  readonly usable: boolean;
  readonly version: string | null;
  readonly compose: string | null;
  readonly error: string;
}

export type Engines = Readonly<Partial<Record<ContainerEngine, EngineReport>>>;

export interface ServerSummary {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
  readonly engines: Engines;
  readonly application_count: number;
  readonly last_check_status: CheckStatus;
  readonly last_checked_at: string | null;
  readonly connection_state: ConnectionState;
  readonly last_seen_at: string | null;
  readonly last_connection_error: string;
}

export interface ServerCheckReport {
  readonly system?: string | null;
  readonly engines?: Engines;
  readonly timeout?: boolean | null;
}

export interface Server {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
  readonly auth_method: AuthMethod;
  readonly has_private_key: boolean;
  readonly has_key_passphrase: boolean;
  readonly has_password: boolean;
  readonly host_key: string;
  readonly host_key_type: string;
  readonly host_key_fingerprint: string;
  readonly engines: Engines;
  readonly last_check_status: CheckStatus;
  readonly last_check_error: string;
  readonly last_checked_at: string | null;
  readonly last_check_report: ServerCheckReport;
  readonly timeout_on_host: boolean | null;
  readonly connection_state: ConnectionState;
  readonly last_seen_at: string | null;
  readonly last_connection_error: string;
  readonly created_at: string;
  readonly updated_at: string;
}

export interface ServerConnection {
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
  readonly auth_method: AuthMethod;
  readonly private_key?: string;
  readonly key_passphrase?: string;
  readonly password?: string;
}

export interface ServerCreate extends ServerConnection {
  readonly host_key: string;
  readonly generate_key?: boolean;
}

export interface ServerUpdate extends Partial<ServerConnection> {
  readonly account_password?: string;
}

export interface CreatedServer extends Server {
  readonly public_key?: string;
  readonly authorized_keys_hint?: string;
}

export interface PublicKey {
  readonly public_key: string;
}

export interface ServerMerge {
  readonly into: string;
  readonly account_password: string;
}

export interface HostKeyTarget {
  readonly host: string;
  readonly port: number;
}

export interface HostKey {
  readonly key_type: string;
  readonly line: string;
  readonly fingerprint: string;
}

export interface HostKeyConfirmation {
  readonly id: string;
  readonly host: string;
  readonly port: number;
  readonly key_type: string;
  readonly fingerprint: string;
  readonly status: 'pending' | 'confirmed' | 'rejected';
  readonly requested_at: string;
  readonly expires_at: string;
}

export type HostKeyDecision = 'confirm' | 'reject';

export interface HostKeyRepin {
  readonly host_key: string;
  readonly password: string;
}

export interface ServerListQuery {
  readonly search: string;
  readonly page: number;
  readonly page_size: number;
}
