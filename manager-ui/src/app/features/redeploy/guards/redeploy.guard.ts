import type { CanActivateFn } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';

// Every action on the page needs at least a rehearsal; a role without one has nothing to do here.
export const redeployGuard: CanActivateFn = capabilityGuard('redeploy.rehearse');
