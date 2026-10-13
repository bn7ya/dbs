import { inject } from '@angular/core';
import { Router, type ActivatedRouteSnapshot, type CanActivateFn, type RouterStateSnapshot, type UrlTree } from '@angular/router';

import { SetupStore } from '@core/setup/state/setup.store';
import type { Capability, SignInStepName } from '../data/auth.types';
import { AuthStore } from '../state/auth.store';

const PASSWORD_PAGE = '/password';

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
    return auth.passwordChangeRequired() ? router.createUrlTree([PASSWORD_PAGE]) : true;
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

export function stepGuard(step: SignInStepName): CanActivateFn {
  return (route: ActivatedRouteSnapshot) => {
    const auth = inject(AuthStore);
    const router = inject(Router);
    if (auth.step() === step || (step === 'enroll' && auth.recoveryCodes() !== null)) {
      return true;
    }
    const next = route.queryParamMap.get('next');
    return router.createUrlTree(['/sign-in'], next ? { queryParams: { next } } : {});
  };
}

export const passwordGuard: CanActivateFn = async (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
  const auth = inject(AuthStore);
  const router = inject(Router);

  const signedIn = await ensureSignedIn(route, state);
  if (signedIn !== true && router.serializeUrl(signedIn) !== PASSWORD_PAGE) {
    return signedIn;
  }
  return auth.passwordChangeRequired() ? true : router.createUrlTree(['/account']);
};

export function capabilityGuard(capability: Capability): CanActivateFn {
  return async (route: ActivatedRouteSnapshot, state: RouterStateSnapshot) => {
    const auth = inject(AuthStore);
    const router = inject(Router);

    const signedIn = await ensureSignedIn(route, state);
    if (signedIn !== true) {
      return signedIn;
    }

    return auth.can(capability) ? true : router.createUrlTree(['/forbidden']);
  };
}

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
