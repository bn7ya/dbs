import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { MatIconButton } from '@angular/material/button';
import { MAT_SNACK_BAR_DATA, MatSnackBarLabel, MatSnackBarRef } from '@angular/material/snack-bar';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { TOAST_ICON, type ToastMessage } from '../toaster.types';

@Component({
  selector: 'app-toast',
  imports: [MatIconButton, MatSnackBarLabel, TranslatePipe],
  templateUrl: './toast.html',
  styleUrl: './toast.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class]': '"toast toast--" + message.severity' },
})
export class Toast {
  protected readonly message = inject<ToastMessage>(MAT_SNACK_BAR_DATA);
  private readonly ref = inject(MatSnackBarRef);

  protected readonly icon = computed(() => TOAST_ICON[this.message.severity]);

  dismiss(): void {
    this.ref.dismiss();
  }
}
