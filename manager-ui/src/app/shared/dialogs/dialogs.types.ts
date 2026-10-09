import type { Type } from '@angular/core';
import type { Observable } from 'rxjs';

export type DialogSize = 'sm' | 'md' | 'lg';

export interface DialogOptions<D> {
  readonly titleKey: string;
  readonly data?: D;
  readonly size?: DialogSize;
}

export interface DialogHandle<R> {
  readonly closed: Observable<R | undefined>;
  whenClosed(): Promise<R | undefined>;
}

export interface DialogPayload<D> {
  readonly titleKey: string;
  readonly component: Type<unknown>;
  readonly data: D;
}
