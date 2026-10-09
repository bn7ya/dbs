import { ChangeDetectionStrategy, Component, computed, forwardRef, inject, input, signal } from '@angular/core';
import { NG_VALUE_ACCESSOR, type ControlValueAccessor } from '@angular/forms';
import { ButtonDirective } from 'primeng/button';
import { InputPassword } from 'primeng/inputpassword';

import { LocaleStore } from '@core/i18n/locale.store';
import { Field } from '../field/field';

@Component({
  selector: 'app-password-input',
  imports: [ButtonDirective, InputPassword],
  providers: [{ provide: NG_VALUE_ACCESSOR, useExisting: forwardRef(() => PasswordInput), multi: true }],
  templateUrl: './password-input.html',
  styleUrl: './password-input.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PasswordInput implements ControlValueAccessor {
  private readonly locale = inject(LocaleStore);
  protected readonly field = inject(Field, { optional: true });

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
