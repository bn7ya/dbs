import type { Signal } from '@angular/core';

import type { ApiError } from '@core/http/api.types';
import type { DeploymentProfile } from '../../data/applications.types';

export interface DeploymentDialogData {
  readonly profile: DeploymentProfile;
  readonly detected: DeploymentProfile | null;
  readonly save: (profile: DeploymentProfile) => Promise<boolean>;
  readonly error: Signal<ApiError | null>;
}
