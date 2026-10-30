import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { Can } from '@core/auth/directives/can';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { CopyButton } from '@shared/copy-button/copy-button';
import { Dialogs } from '@shared/dialogs/dialogs';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastSeverity } from '@shared/toaster/toaster.types';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { EnginesReport } from '../../components/engines-report/engines-report';
import { HostKeyFacts } from '../../components/host-key-facts/host-key-facts';
import { HostKeyReview } from '../../components/host-key-review/host-key-review';
import { ServerForm } from '../../components/server-form/server-form';
import type { ServerFormData } from '../../components/server-form/server-form.types';
import type { Server } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import type { SettingRow } from './server-overview.types';

@Component({
  selector: 'app-server-overview-page',
  imports: [
    Can,
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatInput,
    AppDatePipe,
    CheckStatusTag,
    CopyButton,
    EnginesReport,
    HostKeyFacts,
    Notice,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './server-overview.html',
  styleUrl: './server-overview.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerOverviewPage {
  private readonly store = inject(ServersStore);
  private readonly dialogs = inject(Dialogs);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);

  readonly server = this.store.server;
  readonly checking = this.store.checking;
  readonly checkFailure = this.store.checkFailure;
  readonly hostKeyChanged = this.store.hostKeyChanged;
  readonly publicKey = this.store.publicKey;
  readonly readingKey = this.store.readingKey;
  readonly keyError = this.store.keyError;
  readonly twins = this.store.twins;
  readonly merging = this.store.merging;
  readonly deleting = this.store.deleting;

  readonly reported = computed(() => {
    const status = this.server()?.last_check_status;
    return status === 'ok' || status === 'problem';
  });

  readonly settings = computed<readonly SettingRow[]>(() => {
    const server = this.server();
    return server ? settingRows(server) : [];
  });

  readonly authorizedKeys = computed(() => isolated(`~${this.server()?.username ?? ''}/.ssh/authorized_keys`));

  constructor() {
    this.store.watchTwins(true);
    inject(DestroyRef).onDestroy(() => {
      this.store.watchTwins(false);
      this.store.hidePublicKey();
    });
  }

  async check(): Promise<void> {
    if (await this.store.check()) {
      this.notify('success', 'servers.check.done');
    }
  }

  async edit(): Promise<void> {
    const server = this.server();
    if (!server) {
      return;
    }
    const saved = await this.dialogs
      .open<Server, ServerFormData>(ServerForm, { titleKey: 'servers.form.editTitle', data: { server }, size: 'md' })
      .whenClosed();
    if (saved) {
      this.notify('success', 'servers.settings.updated');
    }
  }

  async reviewHostKey(): Promise<void> {
    const pinned = await this.dialogs
      .open<boolean>(HostKeyReview, { titleKey: 'servers.review.title', size: 'md' })
      .whenClosed();
    if (pinned) {
      this.notify('success', 'servers.review.done');
    }
  }

  async togglePublicKey(): Promise<void> {
    if (this.publicKey()) {
      this.store.hidePublicKey();
      return;
    }
    await this.store.readPublicKey();
  }

  async merge(into: Server): Promise<void> {
    const server = this.server();
    if (!server) {
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'servers.merge.title',
      bodyKey: 'servers.merge.prompt',
      bodyValues: { name: isolated(server.name), into: isolated(into.name) },
      submitKey: 'servers.merge.action',
      submit: (password) => this.store.merge(into.id, password),
      error: this.store.mergeError,
    };
    const merged = await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    if (merged) {
      this.notify('success', 'servers.merge.done');
      await this.router.navigate(['/servers', into.id]);
    }
  }

  async remove(): Promise<void> {
    const server = this.server();
    if (!server) {
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'servers.delete.title',
      bodyKey: 'servers.delete.prompt',
      bodyValues: { name: isolated(server.name) },
      submitKey: 'servers.delete.action',
      destructive: true,
      submit: (password) => this.store.remove(password),
      error: this.store.deleteError,
    };
    const deleted = await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    if (deleted) {
      this.notify('success', 'servers.delete.done');
      await this.router.navigate(['/servers']);
    }
  }

  private notify(severity: ToastSeverity, key: string): void {
    this.toaster.add({ severity, summary: this.locale.translate(key) });
  }
}

function savedRow(labelKey: string, saved: boolean): SettingRow {
  return { labelKey, textKey: saved ? 'servers.settings.saved' : 'servers.settings.notSaved' };
}

function settingRows(server: Server): readonly SettingRow[] {
  const secrets =
    server.auth_method === 'key'
      ? [
          savedRow('servers.settings.privateKey', server.has_private_key),
          savedRow('servers.settings.keyPassphrase', server.has_key_passphrase),
        ]
      : [savedRow('servers.settings.password', server.has_password)];
  return [
    { labelKey: 'servers.settings.host', code: server.host },
    { labelKey: 'servers.settings.port', code: String(server.port) },
    { labelKey: 'servers.settings.username', code: server.username },
    { labelKey: 'servers.settings.authMethod', textKey: `servers.authMethod.${server.auth_method}` },
    ...secrets,
  ];
}
