import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { MatButton } from '@angular/material/button';

import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '../toaster/toaster';

@Component({
  selector: 'app-copy-button',
  imports: [MatButton],
  templateUrl: './copy-button.html',
  styleUrl: './copy-button.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CopyButton {
  private readonly clipboard = inject(DOCUMENT).defaultView?.navigator.clipboard;
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);

  readonly text = input.required<string>();
  readonly label = input.required<string>();

  async copy(): Promise<void> {
    try {
      if (!this.clipboard) {
        throw new Error('No clipboard');
      }
      await this.clipboard.writeText(this.text());
      this.toaster.add({ severity: 'success', summary: this.locale.translate('copy.done') });
    } catch {
      this.toaster.add({ severity: 'warning', summary: this.locale.translate('copy.unavailable') });
    }
  }
}
