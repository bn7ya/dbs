import type { CanActivateFn } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';

export const relocationGuard: CanActivateFn = capabilityGuard('relocation.rehearse');
