import type { SignInStepName } from '@core/auth/data/auth.types';

export interface SetupStatus {
  readonly needed: boolean;
}

export interface SetupRequest {
  readonly token: string;
  readonly username: string;
  readonly password: string;
}

export interface SetupResult {
  readonly username: string;
  readonly step: SignInStepName;
}
