import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButton } from '@angular/material/button';
import { MatError, MatFormField, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { FieldError } from '@shared/field/field-error';
import { Notice } from '@shared/notice/notice';
import { folderNameProblem, type Entry } from '../../data/files.types';
import { FilesStore } from '../../state/files.store';
import type { NewFolderData } from './new-folder.types';

const NAME_FAILURES: ReadonlySet<string> = new Set(['file_exists']);

@Component({
  selector: 'app-new-folder',
  imports: [
    FormsModule,
    MatButton,
    MatFormField,
    MatLabel,
    MatError,
    MatInput,
    FieldError,
    Notice,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './new-folder.html',
  styleUrl: './new-folder.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NewFolderDialog {
  private readonly store = inject(FilesStore);
  private readonly ref = injectDialogRef<Entry>();
  protected readonly data = injectDialogData<NewFolderData>();

  // LRI ... PDI: the path reads left to right inside a sentence of either language.
  protected readonly where = `⁦${this.data.folder}⁩`;

  readonly name = signal('');
  private readonly submitted = signal(false);
  readonly busy = this.store.creating;

  readonly problem = computed(() => (this.submitted() ? folderNameProblem(this.name()) : null));

  private readonly failure = computed<ApiError | null>(() => (this.submitted() && !this.busy() ? this.store.createError() : null));

  readonly nameFailure = computed(() => {
    const failure = this.failure();
    if (failure === null) {
      return null;
    }
    return failure.fields?.['name']?.[0] ?? (NAME_FAILURES.has(failure.code) ? failure.code : null);
  });

  readonly otherFailure = computed(() => (this.nameFailure() === null ? this.failure() : null));

  onName(name: string): void {
    this.name.set(name);
    this.store.resetNewFolder();
  }

  async submit(): Promise<void> {
    this.submitted.set(true);
    if (folderNameProblem(this.name()) !== null || this.busy()) {
      return;
    }
    const created = await this.store.createFolder(this.data.folder, this.name().trim());
    if (created !== null) {
      this.ref.close(created);
    }
  }

  cancel(): void {
    this.ref.close();
  }
}
