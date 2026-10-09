import type { CanActivateFn } from '@angular/router';

import { authGuard } from '@core/auth/guards/auth.guard';

// Its own guard, not `authGuard` in the route, so narrowing the list to a group is a change here only.
export const activityGuard: CanActivateFn = (route, state) => authGuard(route, state);
