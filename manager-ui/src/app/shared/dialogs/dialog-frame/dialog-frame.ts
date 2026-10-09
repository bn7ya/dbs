import { NgComponentOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatIconButton } from '@angular/material/button';
import { MAT_DIALOG_DATA, MatDialogClose, MatDialogContent, MatDialogTitle } from '@angular/material/dialog';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { DialogPayload } from '../dialogs.types';

@Component({
  selector: 'app-dialog-frame',
  imports: [NgComponentOutlet, MatIconButton, MatDialogTitle, MatDialogContent, MatDialogClose, TranslatePipe],
  templateUrl: './dialog-frame.html',
  styleUrl: './dialog-frame.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DialogFrame {
  protected readonly payload = inject<DialogPayload<unknown>>(MAT_DIALOG_DATA);
}
