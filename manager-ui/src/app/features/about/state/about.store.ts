import { Injectable, computed, inject, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';

import { apiErrorOf } from '@core/http/api-error';
import type { ApiError } from '@core/http/api.types';
import { AboutApi } from '../data/about.api';
import type { About, ManagerInstall, ManagerRelease } from '../data/about.types';

@Injectable()
export class AboutStore {
  private readonly api = inject(AboutApi);

  private readonly resource = rxResource({ stream: () => this.api.get() });

  readonly about = computed<About | undefined>(() => (this.resource.hasValue() ? this.resource.value() : undefined));

  readonly loading = this.resource.isLoading;
  readonly error = computed(() => apiErrorOf(this.resource.error()));
  readonly pending = computed(() => this.about() === undefined && this.loading());

  reload(): void {
    this.resource.reload();
  }

  readonly update = signal<ManagerRelease | null>(null);
  readonly looking = signal(false);
  readonly lookError = signal<ApiError | null>(null);
  readonly installed = signal<ManagerInstall | null>(null);
  readonly installError = signal<ApiError | null>(null);

  async lookForUpdate(): Promise<void> {
    if (this.looking()) {
      return;
    }
    this.looking.set(true);
    this.lookError.set(null);
    try {
      this.update.set(await firstValueFrom(this.api.release()));
    } catch (error) {
      this.lookError.set(error as ApiError);
    } finally {
      this.looking.set(false);
    }
  }

  async install(password: string): Promise<boolean> {
    this.installError.set(null);
    try {
      this.installed.set(await firstValueFrom(this.api.install(password)));
    } catch (error) {
      this.installError.set(error as ApiError);
      return false;
    }
    return true;
  }
}
