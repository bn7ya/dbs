import type { ContainerEngine } from '../../data/servers.types';

export type EngineState = 'absent' | 'denied' | 'broken' | 'ready';

export interface EngineView {
  readonly engine: ContainerEngine;
  readonly state: EngineState;
  readonly version: string | null;
  readonly compose: string | null;
  readonly said: string;
}

export interface EngineLook {
  readonly icon: string;
  readonly muted: boolean;
}
