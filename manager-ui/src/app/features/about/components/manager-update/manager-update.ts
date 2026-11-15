import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Dialogs } from '@shared/dialogs/dialogs';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { uniqueId } from '@shared/unique-id';
import { AboutStore } from '../../state/about.store';

@Component({
  selector: 'app-manager-update',
  imports: [MatButton, Notice, ErrorTextPipe, TranslatePipe],
  templateUrl: './manager-update.html',
  styleUrl: './manager-update.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ManagerUpdate {
  private readonly store = inject(AboutStore);
  private readonly dialogs = inject(Dialogs);
  private readonly document = inject(DOCUMENT);

  readonly headingId = uniqueId('about-update');

  readonly found = this.store.update;
  readonly looking = this.store.looking;
  readonly lookError = this.store.lookError;
  readonly installed = this.store.installed;

  look(): void {
    void this.store.lookForUpdate();
  }

  async install(release: string): Promise<void> {
    const data: PasswordPromptData = {
      titleKey: 'about.update.password.title',
      bodyKey: 'about.update.password.body',
      bodyValues: { version: release },
      submitKey: 'about.update.password.submit',
      submit: (password) => this.store.install(password),
      error: this.store.installError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  reload(): void {
    this.document.defaultView?.location.reload();
  }
}
