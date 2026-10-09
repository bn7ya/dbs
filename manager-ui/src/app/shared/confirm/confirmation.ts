import { Injectable, inject } from '@angular/core';
import { ConfirmationService } from 'primeng/api';

import type { ConfirmOptions } from './confirmation.types';

@Injectable({ providedIn: 'root' })
export class Confirmation {
  private readonly service = inject(ConfirmationService);

  ask(options: ConfirmOptions): Promise<boolean> {
    return new Promise<boolean>((resolve) => {
      this.service.confirm({
        header: options.title,
        message: options.detail ? `${options.message}\n${options.detail}` : options.message,
        acceptLabel: options.acceptLabel,
        rejectLabel: options.rejectLabel,
        acceptButtonProps: { severity: options.acceptSeverity === 'danger' ? 'danger' : undefined },
        rejectButtonProps: { severity: 'secondary', outlined: true },
        accept: () => resolve(true),
        reject: () => resolve(false),
      });
    });
  }
}
