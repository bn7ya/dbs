import type { CanActivateFn } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';

export const consoleGuard: CanActivateFn = capabilityGuard('console.run');
