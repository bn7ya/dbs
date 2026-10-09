import { Injectable, inject } from '@angular/core';
import { MessageService } from 'primeng/api';

import type { ToastMessage, ToastSeverity } from './toaster.types';

const PRIME_SEVERITY: Readonly<Record<ToastSeverity, 'success' | 'info' | 'warn' | 'error'>> = {
  success: 'success',
  info: 'info',
  warning: 'warn',
  danger: 'error',
};

@Injectable({ providedIn: 'root' })
export class Toaster {
  private readonly messages = inject(MessageService);

  add(message: ToastMessage): void {
    this.messages.add({ severity: PRIME_SEVERITY[message.severity], summary: message.summary, detail: message.detail });
  }
}
