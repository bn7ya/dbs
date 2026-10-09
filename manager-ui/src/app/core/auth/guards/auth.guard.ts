import { inject } from '@angular/core';
import { Router, type ActivatedRouteSnapshot, type CanActivateFn, type RouterStateSnapshot, type UrlTree } from '@angular/router';

import { SetupStore } from '@core/setup/state/setup.store';
import { AuthStore } from '../state/auth.store';

async function setupRedirect(
  setup: SetupStore,
  router: Router,
  route: ActivatedRouteSnapshot,
): Promise<UrlTree | null> {
  if (!(await setup.check())) {
    return null;
  }
  const token = route.queryParamMap.get('token');
  return router.createUrlTree(['/setup'], token ? { queryParams: { token } } : {});
}

async function ensureSignedIn(route: ActivatedRouteSnapshot, state: RouterStateSnapshot): Promise<true | UrlTree> {
  const auth = inject(AuthStore);
  const setup = inject(SetupStore);
  const router = inject(Router);

  if (!auth.resolved()) {
    await auth.restore();
  }

  if (auth.isAuthenticated()) {
    return true;
  }

  return (
    (await setupRedirect(setup, router, route)) ??
    router.createUrlTree(['/sign-in'], { queryParams: { next: state.url } })
  );
}

export const authGuard: CanActivateFn = (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) =>
  ensureSignedIn(route, state);

export const guestGuard: CanActivateFn = async (route: ActivatedRouteSnapshot) => {
  const auth = inject(AuthStore);
  const setup = inject(SetupStore);
  const router = inject(Router);

  if (!auth.resolved()) {
    await auth.restore();
  }

  if (auth.isAuthenticated()) {
    return router.createUrlTree(['/']);
  }

  return (await setupRedirect(setup, router, route)) ?? true;
};

export function groupGuard(...groups: readonly string[]): CanActivateFn {
  return async (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
    const auth = inject(AuthStore);
    const router = inject(Router);

    const signedIn = await ensureSignedIn(route, state);
    if (signedIn !== true) {
      return signedIn;
    }

    return auth.hasAnyGroup(groups) ? true : router.createUrlTree(['/forbidden']);
  };
}
