import type { CanActivateFn } from '@angular/router';

import { capabilityGuard } from '@core/auth/guards/auth.guard';

export const terminalGuard: CanActivateFn = capabilityGuard('shell.open');
