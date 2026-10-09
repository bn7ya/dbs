import { ChangeDetectionStrategy, Component, computed, forwardRef, inject, input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';
import { MatIconButton } from '@angular/material/button';
import { MatError, MatFormField, MatHint, MatLabel, MatSuffix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { LocaleStore } from '@core/i18n/locale.store';
import { FieldError } from '../field/field-error';

@Component({
  selector: 'app-password-input',
  imports: [MatFormField, MatLabel, MatHint, MatError, MatSuffix, MatInput, MatIconButton, FieldError],
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => PasswordInput), multi: true }],
  templateUrl: './password-input.html',
  styleUrl: './password-input.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PasswordInput implements ControlValueAccessor {
  private readonly locale = inject(LocaleStore);

  readonly label = input.required<string>();
  readonly hint = input('');
  readonly error = input<string | null | undefined>('');
  readonly autocomplete = input('current-password');
  readonly placeholder = input('');
  readonly name = input('');

  protected readonly value = signal('');
  protected readonly masked = signal(true);
  protected readonly disabled = signal(false);

  protected readonly toggleLabel = computed(() =>
    this.locale.translate(this.masked() ? 'auth.signIn.showPassword' : 'auth.signIn.hidePassword'),
  );

  private onChange: (value: string) => void = () => undefined;
  private onTouched: () => void = () => undefined;

  writeValue(value: string | null): void {
    this.value.set(value ?? '');
  }

  registerOnChange(fn: (value: string) => void): void {
    this.onChange = fn;
  }

  registerOnTouched(fn: () => void): void {
    this.onTouched = fn;
  }

  setDisabledState(disabled: boolean): void {
    this.disabled.set(disabled);
  }

  protected input(event: Event): void {
    const value = (event.target as HTMLInputElement).value;
    this.value.set(value);
    this.onChange(value);
  }

  protected touch(): void {
    this.onTouched();
  }

  protected toggle(): void {
    this.masked.update((masked) => !masked);
  }
}
