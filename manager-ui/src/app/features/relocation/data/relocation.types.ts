import type { StepStatus } from '@shared/steps-list/steps-list.types';

export type MoveKind = 'host' | 'compose' | 'container';

export interface MoveServer {
  readonly id: string;
  readonly name: string;
  readonly host: string;
  readonly port: number;
  readonly username: string;
}

export interface MoveApplication {
  readonly id: string;
  readonly name: string;
  readonly kind: MoveKind;
  readonly engine: string;
  readonly project_dir: string;
}

export interface MoveChoice {
  readonly application: string;
  readonly name: string;
  readonly folder: string;
  readonly skip_volumes: readonly string[];
  readonly copy_plans: boolean;
}

export interface ChoiceDraft {
  readonly application: MoveApplication;
  readonly selected: boolean;
  readonly name: string;
  readonly folder: string;
}

export interface ServerMoveRequest {
  readonly target_server: string;
  readonly applications: readonly MoveChoice[];
  readonly rehearsal: boolean;
  readonly password: string;
  readonly confirm_name: string;
  readonly sudo_password: string;
  readonly source_sudo_password: string;
  readonly resume_of?: number;
}

export interface MoveFact {
  readonly code: string;
  readonly application?: string;
  readonly path?: string;
  readonly volume?: string;
  readonly image?: string;
  readonly name?: string;
  readonly site?: string;
  readonly source?: string;
  readonly target?: string;
}

export interface PlannedFolder {
  readonly path: string;
  readonly target: string;
  readonly bytes: number | null;
  readonly excluded: readonly string[];
}

export interface PlannedGit {
  readonly head: string;
  readonly branch: string;
  readonly remote: string;
  readonly dirty: number | null;
}

export interface PlannedImage {
  readonly ref: string;
  readonly bytes: number | null;
  readonly on_target: boolean;
}

export interface PlannedVolume {
  readonly name: string;
  readonly bytes: number | null;
  readonly selected: boolean;
  readonly reason: string;
}

export interface PlannedBind {
  readonly source: string;
  readonly target: string;
  readonly bytes: number | null;
  readonly selected: boolean;
}

export interface PlannedDatabase {
  readonly vendor?: string;
  readonly placement?: string;
  readonly action?: string;
}

export interface PlannedService {
  readonly name: string;
}

export interface PlannedPython {
  readonly action?: string;
  readonly version?: string;
  readonly target_version?: string;
}

export interface PlannedApplication {
  readonly application: string;
  readonly name: string;
  readonly target_name: string;
  readonly kind: MoveKind;
  readonly folder: PlannedFolder;
  readonly git: PlannedGit | null;
  readonly images: readonly PlannedImage[];
  readonly volumes: readonly PlannedVolume[];
  readonly binds: readonly PlannedBind[];
  readonly database: PlannedDatabase;
  readonly units: readonly PlannedService[];
  readonly sites: readonly PlannedService[];
  readonly python: PlannedPython;
  readonly blockers: readonly MoveFact[];
  readonly notes: readonly MoveFact[];
}

export interface PlannedSystem {
  readonly distribution: string;
  readonly version: string;
  readonly architecture: string;
  readonly supported: boolean;
}

export interface PlannedPackages {
  readonly packages: readonly string[];
  readonly repositories: readonly string[];
}

export interface NeedsSudo {
  readonly target: boolean;
  readonly source: boolean;
}

export interface MoveInventory {
  readonly target: { readonly system: PlannedSystem | null; readonly sudo: string };
  readonly packages: PlannedPackages;
  readonly applications: readonly PlannedApplication[];
  readonly needs_sudo: NeedsSudo;
  readonly totals: { readonly bytes: number };
  readonly notes: readonly MoveFact[];
}

export interface MoveStep {
  readonly step: string;
  readonly status: StepStatus;
  readonly key?: string;
  readonly warning?: string;
  readonly reason?: string;
}

export type MovePhaseKind = 'plan' | 'prepare' | 'application';

export interface MovePhase {
  readonly phase: MovePhaseKind;
  readonly name?: string;
  readonly target_name?: string;
  readonly status: StepStatus;
  readonly steps: readonly MoveStep[];
}

export interface CreatedApplication {
  readonly source: string;
  readonly target: string;
  readonly name: string;
}

export interface MoveCurrent {
  readonly step: string;
  readonly key: string;
  readonly bytes?: number;
  readonly total?: number | null;
}

export interface MoveDetail {
  readonly rehearsal: boolean;
  readonly inventory: MoveInventory | null;
  readonly phases: readonly MovePhase[];
  readonly blockers: readonly MoveFact[];
  readonly leftovers: readonly string[];
  readonly created: readonly CreatedApplication[];
  readonly current: MoveCurrent | null;
}
