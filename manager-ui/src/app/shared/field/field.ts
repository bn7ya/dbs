import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { uniqueId } from '../unique-id';

@Component({
  selector: 'app-field',
  exportAs: 'appField',
  templateUrl: './field.html',
  styleUrl: './field.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Field {
  readonly label = input.required<string>();
  readonly hint = input('');
  readonly error = input('');
  readonly required = input(false);

  readonly id = uniqueId('field');
  readonly hintId = `${this.id}-hint`;
  readonly errorId = `${this.id}-error`;

  readonly invalid = computed(() => this.error() !== '');

  readonly describedBy = computed<string | null>(() => {
    const ids = [this.hint() !== '' ? this.hintId : '', this.invalid() ? this.errorId : ''].filter((id) => id !== '');
    return ids.length > 0 ? ids.join(' ') : null;
  });
}
