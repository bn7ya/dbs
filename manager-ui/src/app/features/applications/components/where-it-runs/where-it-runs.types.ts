import type { ApplicationEngine, ApplicationKind } from '../../data/applications.types';

export interface RunPlace {
  readonly kind: ApplicationKind;
  readonly engine: ApplicationEngine;
  readonly project_dir: string;
  readonly compose_service: string;
  readonly container_name: string;
}
