import { Directive, effect, inject, input } from '@angular/core';
import { MatChipGrid } from '@angular/material/chips';
import type { ErrorStateMatcher } from '@angular/material/core';
import { MatInput } from '@angular/material/input';
import { MatSelect } from '@angular/material/select';

@Directive({
  selector: '[appFieldError]',
})
export class FieldError {
  readonly appFieldError = input<string | null | undefined>('');

  private readonly control: MatInput | MatSelect | MatChipGrid | null =
    inject(MatInput, { self: true, optional: true }) ??
    inject(MatSelect, { self: true, optional: true }) ??
    inject(MatChipGrid, { self: true, optional: true });

  private readonly matcher: ErrorStateMatcher = {
    isErrorState: () => (this.appFieldError() ?? '') !== '',
  };

  constructor() {
    const control = this.control;
    if (control) {
      control.errorStateMatcher = this.matcher;
    }
    effect(() => {
      this.appFieldError();
      control?.updateErrorState();
    });
  }
}
