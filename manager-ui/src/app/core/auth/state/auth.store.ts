import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { CsrfToken } from '@core/http/csrf-token';
import type { ApiError } from '@core/http/api.types';
import { AuthApi } from '../data/auth.api';
import type {
  Capability,
  Credentials,
  Enrollment,
  Identity,
  PasswordChange,
  SecondFactor,
  SignInStepName,
} from '../data/auth.types';

@Injectable({ providedIn: 'root' })
export class AuthStore {
  private readonly api = inject(AuthApi);
  private readonly router = inject(Router);
  private readonly csrf = inject(CsrfToken);

  private readonly identity = signal<Identity | null>(null);
  private readonly pendingStep = signal<SignInStepName | null>(null);
  private readonly enrollmentShown = signal<Enrollment | null>(null);
  private readonly freshCodes = signal<readonly string[] | null>(null);

  readonly resolved = signal(false);
  readonly busy = signal(false);
  readonly error = signal<ApiError | null>(null);

  readonly user = this.identity.asReadonly();
  readonly step = this.pendingStep.asReadonly();
  readonly enrollment = this.enrollmentShown.asReadonly();
  readonly recoveryCodes = this.freshCodes.asReadonly();
  readonly isAuthenticated = computed(() => this.identity() !== null);
  readonly role = computed(() => this.identity()?.role ?? null);
  readonly passwordChangeRequired = computed(() => this.identity()?.password_change_required ?? false);
  readonly groups = computed<readonly string[]>(() => this.identity()?.groups ?? []);
  readonly displayName = computed(() => {
    const user = this.identity();
    if (!user) {
      return '';
    }
    const full = [user.first_name, user.last_name].filter(Boolean).join(' ');
    return full || user.username;
  });

  async restore(): Promise<void> {
    try {
      this.identity.set(await firstValueFrom(this.api.me()));
    } catch {
      this.identity.set(null);
    } finally {
      this.resolved.set(true);
    }
  }

  async signIn(credentials: Credentials): Promise<SignInStepName | null> {
    return this.run(async () => {
      await firstValueFrom(this.api.primeCsrf());
      const { step } = await firstValueFrom(this.api.signIn(credentials));
      this.begin(step);
      return step;
    });
  }

  begin(step: SignInStepName): void {
    this.identity.set(null);
    this.enrollmentShown.set(null);
    this.freshCodes.set(null);
    this.pendingStep.set(step);
  }

  async secondFactor(factor: SecondFactor): Promise<boolean> {
    const signedIn = await this.run(async () => {
      this.signedIn(await firstValueFrom(this.api.secondFactor(factor)));
      return true;
    });
    return signedIn ?? false;
  }

  async startEnrollment(): Promise<boolean> {
    const started = await this.run(async () => {
      this.enrollmentShown.set(await firstValueFrom(this.api.enrollment()));
      return true;
    });
    return started ?? false;
  }

  async enroll(code: string): Promise<boolean> {
    const enrolled = await this.run(async () => {
      const { identity, recovery_codes } = await firstValueFrom(this.api.enroll(code));
      this.freshCodes.set(recovery_codes);
      this.signedIn(identity);
      return true;
    });
    return enrolled ?? false;
  }

  async changePassword(change: PasswordChange): Promise<boolean> {
    const changed = await this.run(async () => {
      this.identity.set(await firstValueFrom(this.api.changePassword(change)));
      return true;
    });
    return changed ?? false;
  }

  async newRecoveryCodes(password: string): Promise<boolean> {
    const made = await this.run(async () => {
      const { recovery_codes } = await firstValueFrom(this.api.newRecoveryCodes(password));
      this.freshCodes.set(recovery_codes);
      await this.restore();
      return true;
    });
    return made ?? false;
  }

  dismissRecoveryCodes(): void {
    this.freshCodes.set(null);
  }

  clearError(): void {
    this.error.set(null);
  }

  async signOut(): Promise<void> {
    this.busy.set(true);
    try {
      await firstValueFrom(this.api.signOut());
    } catch {
      // The session is discarded either way; a failed call must not strand the user.
    } finally {
      this.forget();
      this.busy.set(false);
      await this.router.navigate(['/sign-in']);
    }
  }

  forget(): void {
    this.identity.set(null);
    this.pendingStep.set(null);
    this.enrollmentShown.set(null);
    this.freshCodes.set(null);
    this.csrf.forget();
  }

  can(capability: Capability): boolean {
    return this.identity()?.capabilities.includes(capability) ?? false;
  }

  forbids(capability: Capability): boolean {
    const user = this.identity();
    return user !== null && !user.capabilities.includes(capability);
  }

  hasGroup(name: string): boolean {
    const user = this.identity();
    if (!user) {
      return false;
    }
    return user.is_superuser || user.groups.includes(name);
  }

  hasAnyGroup(names: readonly string[]): boolean {
    return names.some((name) => this.hasGroup(name));
  }

  hasPermission(codename: string): boolean {
    const user = this.identity();
    if (!user) {
      return false;
    }
    return user.is_superuser || user.permissions.includes(codename);
  }

  private signedIn(identity: Identity): void {
    this.identity.set(identity);
    this.pendingStep.set(null);
    this.enrollmentShown.set(null);
    this.csrf.forget();
  }

  private async run<T>(work: () => Promise<T>): Promise<T | null> {
    this.busy.set(true);
    this.error.set(null);
    try {
      return await work();
    } catch (error) {
      const failure = error as ApiError;
      if (failure.code === 'sign_in_expired') {
        this.pendingStep.set(null);
      }
      this.error.set(failure);
      return null;
    } finally {
      this.busy.set(false);
    }
  }
}
