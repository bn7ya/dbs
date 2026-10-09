import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Toast } from './toast/toast';
import { TOAST_DURATION_MS, type ToastMessage } from './toaster.types';

@Injectable({ providedIn: 'root' })
export class Toaster {
  private readonly snackBar = inject(MatSnackBar);

  add(message: ToastMessage): void {
    this.snackBar.openFromComponent(Toast, {
      data: message,
      duration: TOAST_DURATION_MS,
      horizontalPosition: 'end',
      verticalPosition: 'top',
      politeness: message.severity === 'danger' ? 'assertive' : 'polite',
    });
  }
}
