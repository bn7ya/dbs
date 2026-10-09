import { inject } from '@angular/core';
import { Router, type CanActivateFn } from '@angular/router';

import { SetupStore } from '../state/setup.store';

export const setupGuard: CanActivateFn = async () => {
  const setup = inject(SetupStore);
  const router = inject(Router);

  return (await setup.check()) ? true : router.createUrlTree(['/']);
};
