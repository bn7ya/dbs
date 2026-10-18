import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { MatChipGrid, MatChipInput, MatChipRemove, MatChipRow, type MatChipInputEvent } from '@angular/material/chips';
import { MatError, MatFormField, MatHint, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import { uniqueId } from '@shared/unique-id';
import type { ApplicationEngine, ApplicationKind, ContainerEngine } from '../../data/applications.types';
import type { EngineOption, KindOption, RuntimeErrors, RuntimeSettings } from './runtime-fields.types';

const KINDS: readonly KindOption[] = [
  { value: 'host', labelKey: 'applications.kind.host' },
  { value: 'compose', labelKey: 'applications.kind.compose' },
  { value: 'container', labelKey: 'applications.kind.container' },
];

const ENGINES: readonly EngineOption[] = [
  { value: 'docker', labelKey: 'applications.engine.docker' },
  { value: 'podman', labelKey: 'applications.engine.podman' },
];

@Component({
  selector: 'app-runtime-fields',
  imports: [
    FormsModule,
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
  readonly kind = input.required<ApplicationKind>();
  readonly engine = input.required<ApplicationEngine>();
  readonly composeProject = input.required<string>();
  readonly composeService = input.required<string>();
  readonly composeFiles = input.required<readonly string[]>();
  readonly containerName = input.required<string>();
  readonly errors = input<RuntimeErrors>({});

  readonly changed = output<Partial<RuntimeSettings>>();

  protected readonly kinds = KINDS;
  protected readonly engines = ENGINES;
  protected readonly separators = [ENTER, COMMA];
  protected readonly engineErrorId = uniqueId('engine-error');

  chooseKind(kind: ApplicationKind | null): void {
    if (kind) {
      this.changed.emit(kind === 'host' ? { kind, engine: '' } : { kind });
    }
  }

  chooseEngine(engine: ContainerEngine | null): void {
    if (engine) {
      this.changed.emit({ engine });
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
