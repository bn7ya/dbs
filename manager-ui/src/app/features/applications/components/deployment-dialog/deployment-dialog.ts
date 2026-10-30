import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { MatButton } from '@angular/material/button';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { Notice } from '@shared/notice/notice';
import type { DeploymentProfile } from '../../data/applications.types';
import { asked } from '../../data/deployment';
import { DeploymentQuestions } from '../deployment-questions/deployment-questions';
import type { DeploymentDialogData } from './deployment-dialog.types';

@Component({
  selector: 'app-deployment-dialog',
  imports: [MatButton, DeploymentQuestions, Notice, ErrorTextPipe, TranslatePipe],
  templateUrl: './deployment-dialog.html',
  styleUrl: './deployment-dialog.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DeploymentDialog {
  protected readonly data = injectDialogData<DeploymentDialogData>();
  private readonly ref = injectDialogRef<boolean>();

  readonly profile = signal<DeploymentProfile>(this.data.profile);
  readonly busy = signal(false);
  readonly submitted = signal(false);

  async save(): Promise<void> {
    if (this.busy()) {
      return;
    }
    this.submitted.set(true);
    this.busy.set(true);
    try {
      if (await this.data.save(asked(this.profile()))) {
        this.ref.close(true);
      }
    } finally {
      this.busy.set(false);
    }
  }

  cancel(): void {
    this.ref.close();
  }
}
