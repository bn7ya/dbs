import { Directive, inject } from '@angular/core';

import { Field } from './field';

@Directive({
  selector: '[appFieldControl]',
  host: {
    '[id]': 'field.id',
    '[attr.aria-describedby]': 'field.describedBy()',
    '[attr.aria-invalid]': 'field.invalid() ? "true" : null',
  },
})
export class FieldControl {
  protected readonly field = inject(Field);
}
