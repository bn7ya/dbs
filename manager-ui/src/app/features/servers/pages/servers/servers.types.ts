import type { ContainerEngine } from '../../data/servers.types';

export interface EngineFound {
  readonly engine: ContainerEngine;
  readonly version: string | null;
  readonly usable: boolean;
}
