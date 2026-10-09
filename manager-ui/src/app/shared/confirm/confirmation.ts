import { Injectable, inject } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { firstValueFrom } from 'rxjs';

import { ConfirmDialog } from './confirm-dialog/confirm-dialog';
import type { ConfirmOptions } from './confirmation.types';

@Injectable({ providedIn: 'root' })
export class Confirmation {
  private readonly dialog = inject(MatDialog);

  async ask(options: ConfirmOptions): Promise<boolean> {
    const ref = this.dialog.open<ConfirmDialog, ConfirmOptions, boolean>(ConfirmDialog, {
      data: options,
      panelClass: ['app-dialog', 'app-dialog--sm'],
      maxWidth: '',
      role: 'alertdialog',
      autoFocus: 'first-tabbable',
      restoreFocus: true,
    });
    return (await firstValueFrom(ref.afterClosed(), { defaultValue: undefined })) === true;
  }
}
