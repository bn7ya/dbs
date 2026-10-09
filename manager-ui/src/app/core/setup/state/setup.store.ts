import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { AuthApi } from '@core/auth/data/auth.api';
import type { ApiError } from '@core/http/api.types';
import { SetupApi } from '../data/setup.api';
import type { SetupRequest } from '../data/setup.types';

@Injectable({ providedIn: 'root' })
export class SetupStore {
  private readonly api = inject(SetupApi);
  private readonly auth = inject(AuthApi);

  private readonly status = signal<boolean | null>(null);

  readonly needed = computed(() => this.status() === true);
  readonly busy = signal(false);
  readonly error = signal<ApiError | null>(null);

  async check(): Promise<boolean> {
    const known = this.status();
    if (known !== null) {
      return known;
    }
    try {
      const { needed } = await firstValueFrom(this.api.status());
      this.status.set(needed);
      return needed;
    } catch {
      return false;
    }
  }

  async complete(request: SetupRequest): Promise<boolean> {
    this.busy.set(true);
    this.error.set(null);
    try {
      await firstValueFrom(this.auth.primeCsrf());
      await firstValueFrom(this.api.complete(request));
      this.status.set(false);
      return true;
    } catch (error) {
      const failure = error as ApiError;
      if (failure.code === 'setup_done') {
        this.status.set(false);
      }
      this.error.set(failure);
      return false;
    } finally {
      this.busy.set(false);
    }
  }
}
