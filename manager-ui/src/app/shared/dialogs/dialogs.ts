import { Injectable, Injector, inject, type Type } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { firstValueFrom, shareReplay, type Observable } from 'rxjs';

import { DialogFrame } from './dialog-frame/dialog-frame';
import type { DialogHandle, DialogOptions, DialogPayload } from './dialogs.types';

@Injectable()
export class Dialogs {
  private readonly dialog = inject(MatDialog);
  private readonly injector = inject(Injector);

  open<R, D = undefined>(component: Type<unknown>, options: DialogOptions<D>): DialogHandle<R> {
    const ref = this.dialog.open<DialogFrame, DialogPayload<D | undefined>, R>(DialogFrame, {
      data: { titleKey: options.titleKey, component, data: options.data },
      injector: this.injector,
      panelClass: ['app-dialog', `app-dialog--${options.size ?? 'md'}`],
      maxWidth: '',
      autoFocus: 'first-tabbable',
      restoreFocus: true,
    });
    const closed: Observable<R | undefined> = ref.afterClosed().pipe(shareReplay(1));
    const result = firstValueFrom(closed, { defaultValue: undefined });
    return { closed, whenClosed: () => result };
  }
}

export function injectDialogData<D>(): D {
  return inject<DialogPayload<D>>(MAT_DIALOG_DATA).data;
}

export function injectDialogRef<R>(): MatDialogRef<unknown, R> {
  return inject<MatDialogRef<unknown, R>>(MatDialogRef);
}
