import { Directionality } from '@angular/cdk/bidi';
import { Injectable, inject } from '@angular/core';
import { MatSnackBar } from '@angular/material/snack-bar';

import { Toast } from './toast/toast';
import { TOAST_DURATION_MS, type ToastMessage } from './toaster.types';

@Injectable({ providedIn: 'root' })
export class Toaster {
  private readonly snackBar = inject(MatSnackBar);
  private readonly directionality = inject(Directionality);

  add(message: ToastMessage): void {
    // The snack bar reads `end` as the right edge unless it is told the direction.
    this.snackBar.openFromComponent(Toast, {
      data: message,
      duration: TOAST_DURATION_MS,
      direction: this.directionality.value,
      horizontalPosition: 'end',
      verticalPosition: 'top',
      politeness: message.severity === 'danger' ? 'assertive' : 'polite',
    });
  }
}
