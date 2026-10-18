import { Injectable, effect, inject } from '@angular/core';
import { MatStepperIntl } from '@angular/material/stepper';

import { LocaleStore } from './locale.store';

@Injectable()
export class AppStepperIntl extends MatStepperIntl {
  private readonly locale = inject(LocaleStore);

  constructor() {
    super();
    effect(() => {
      const t = (key: string): string => this.locale.translate(key);
      this.optionalLabel = t('components.optional');
      this.completedLabel = t('components.completed');
      this.editableLabel = t('components.editable');
      this.changes.next();
    });
  }
}
