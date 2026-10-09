import type { CanActivateFn } from '@angular/router';

import { authGuard } from '@core/auth/guards/auth.guard';

export const aboutGuard: CanActivateFn = (route, state) => authGuard(route, state);
