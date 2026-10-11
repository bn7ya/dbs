import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { MatAutocomplete, MatAutocompleteTrigger, MatOption } from '@angular/material/autocomplete';
import { MatChipGrid, MatChipInput, MatChipRemove, MatChipRow, type MatChipInputEvent } from '@angular/material/chips';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import type { Runtime } from '../../data/servers.types';
import type { RuntimeOption, RuntimeSettings } from './runtime-fields.types';

@Component({
  selector: 'app-runtime-fields',
  imports: [
    FormsModule,
    MatAutocomplete,
    MatAutocompleteTrigger,
    MatOption,
    MatChipGrid,
    MatChipRow,
    MatChipRemove,
    MatChipInput,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatInput,
    MatRadioGroup,
    MatRadioButton,
    FieldError,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './runtime-fields.html',
  styleUrl: './runtime-fields.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RuntimeFields {
  readonly runtime = input.required<Runtime>();
  readonly composeService = input.required<string>();
  readonly composeFiles = input.required<readonly string[]>();
  readonly services = input<readonly string[]>([]);
  readonly serviceError = input<string | null>(null);
  readonly filesError = input<string | null>(null);

  readonly changed = output<Partial<RuntimeSettings>>();

  protected readonly options: readonly RuntimeOption[] = [
    { value: 'host', labelKey: 'servers.runtime.host' },
    { value: 'compose', labelKey: 'servers.runtime.compose' },
  ];
  protected readonly separators = [ENTER, COMMA];

  choose(runtime: Runtime | null): void {
    if (runtime) {
      this.changed.emit({ runtime });
    }
  }

  addFile(event: MatChipInputEvent): void {
    const file = event.value.trim();
    if (file !== '') {
      this.changed.emit({ compose_files: [...this.composeFiles(), file] });
    }
    event.chipInput.clear();
  }

  removeFile(index: number): void {
    this.changed.emit({ compose_files: this.composeFiles().filter((_, position) => position !== index) });
  }
}
