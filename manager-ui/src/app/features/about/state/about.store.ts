import { Injectable, computed, inject } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { apiErrorOf } from '@core/http/api-error';
import { AboutApi } from '../data/about.api';
import type { About } from '../data/about.types';

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
}
