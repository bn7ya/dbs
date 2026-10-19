import { ChangeDetectionStrategy, Component, computed, input, output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { COMMA, ENTER } from '@angular/cdk/keycodes';
import { MatAutocomplete, MatAutocompleteTrigger } from '@angular/material/autocomplete';
import { MatIconButton } from '@angular/material/button';
import { MatButtonToggle, MatButtonToggleGroup } from '@angular/material/button-toggle';
import { MatChipGrid, MatChipInput, MatChipRemove, MatChipRow, type MatChipInputEvent } from '@angular/material/chips';
import { MatOption, type MatOptionSelectionChange } from '@angular/material/core';
import { MatError, MatFormField, MatHint, MatLabel, MatSuffix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import type { EnvCandidate, EnvLocation } from '../../data/applications.types';
import { RuntimeFields } from '../runtime-fields/runtime-fields';
import type { RuntimeErrors, RuntimeSettings } from '../runtime-fields/runtime-fields.types';
import type { BrowsedField } from '../server-browser/server-browser.types';
import type { ApplicationDraft, DraftErrors, LocationOption } from './settings-fields.types';

const LOCATIONS: readonly LocationOption[] = [
  { value: 'host', labelKey: 'applications.envLocation.host' },
  { value: 'container', labelKey: 'applications.envLocation.container' },
];

@Component({
  selector: 'app-settings-fields',
  imports: [
    FormsModule,
    MatAutocomplete,
    MatAutocompleteTrigger,
    MatIconButton,
    MatButtonToggle,
    MatButtonToggleGroup,
    MatChipGrid,
    MatChipRow,
    MatChipRemove,
    MatChipInput,
    MatOption,
    MatError,
    MatFormField,
    MatHint,
    MatLabel,
    MatSuffix,
    MatInput,
    FieldError,
    RuntimeFields,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './settings-fields.html',
  styleUrl: './settings-fields.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SettingsFields {
  readonly draft = input.required<ApplicationDraft>();
  readonly errors = input<DraftErrors>({});
  readonly pythonPaths = input<readonly string[]>([]);
  readonly envCandidates = input<readonly EnvCandidate[]>([]);

  readonly changed = output<Partial<ApplicationDraft>>();
  readonly browse = output<BrowsedField>();

  protected readonly locations = LOCATIONS;
  protected readonly separators = [ENTER, COMMA];

  protected readonly contained = computed(() => this.draft().kind !== 'host');
  protected readonly hostPaths = computed(() => !this.contained());
  protected readonly envOnHost = computed(() => !this.contained() || this.draft().env_location === 'host');
  protected readonly runtimeErrors = computed<RuntimeErrors>(() => {
    const errors = this.errors();
    return {
      engine: errors.engine,
      compose_project: errors.compose_project,
      compose_service: errors.compose_service,
      compose_files: errors.compose_files,
      container_name: errors.container_name,
    };
  });

  update<K extends keyof ApplicationDraft>(field: K, value: ApplicationDraft[K]): void {
    this.changed.emit({ [field]: value });
  }

  updateRuntime(change: Partial<RuntimeSettings>): void {
    this.changed.emit(change);
  }

  setLocation(location: EnvLocation | null): void {
    if (location) {
      this.update('env_location', location);
    }
  }

  pickEnv(event: MatOptionSelectionChange<string>, candidate: EnvCandidate): void {
    if (event.isUserInput) {
      this.changed.emit({ env_path: candidate.path, env_location: candidate.location });
    }
  }

  addFileRoot(event: MatChipInputEvent): void {
    const root = event.value.trim();
    if (root !== '') {
      this.update('file_roots', [...this.draft().file_roots, root]);
    }
    event.chipInput.clear();
  }

  removeFileRoot(index: number): void {
    this.update(
      'file_roots',
      this.draft().file_roots.filter((_, position) => position !== index),
    );
  }
}
