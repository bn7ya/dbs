import type { CanActivateFn } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';

export const accountsGuard: CanActivateFn = capabilityGuard('accounts.manage');
