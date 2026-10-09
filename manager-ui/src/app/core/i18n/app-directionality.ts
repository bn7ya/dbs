import { Directionality } from '@angular/cdk/bidi';
import { Injectable, effect, inject, untracked } from '@angular/core';

import { LocaleStore } from './locale.store';

@Injectable({ providedIn: 'root' })
export class AppDirectionality extends Directionality {
  private readonly locale = inject(LocaleStore);

  constructor() {
    super();
    this.valueSignal.set(this.locale.direction());
    effect(() => {
      const direction = this.locale.direction();
      if (untracked(this.valueSignal) !== direction) {
        this.valueSignal.set(direction);
        this.change.emit(direction);
      }
    });
  }
}
