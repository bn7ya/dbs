import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { MatButton, MatIconButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel, MatSuffix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Toaster } from '@shared/toaster/toaster';
import type { ToastSeverity } from '@shared/toaster/toaster.types';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { HostKeyFacts } from '../../components/host-key-facts/host-key-facts';
import { HostKeyReview } from '../../components/host-key-review/host-key-review';
import { ServerForm } from '../../components/server-form/server-form';
import type { ServerFormData } from '../../components/server-form/server-form.types';
import type { Server } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import type { CheckReportView, Presence, PresenceLook, ReportRow, SettingRow } from './server-overview.types';

const PRESENCE_LOOKS: Readonly<Record<Presence, PresenceLook>> = {
  found: { icon: 'fa-solid fa-circle-check', muted: false },
  missing: { icon: 'fa-solid fa-circle-xmark', muted: false },
  notSet: { icon: 'fa-solid fa-circle-minus', muted: true },
  notChecked: { icon: 'fa-solid fa-circle-question', muted: true },
};

@Component({
  selector: 'app-server-overview-page',
  imports: [
    RouterLink,
    MatButton,
    MatIconButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatSuffix,
    MatInput,
    Notice,
    AppDatePipe,
    CheckStatusTag,
    HostKeyFacts,
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
  private readonly confirmation = inject(Confirmation);
  private readonly toaster = inject(Toaster);
  private readonly clipboard = inject(DOCUMENT).defaultView?.navigator.clipboard;
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);

  readonly server = this.store.server;
  readonly checking = this.store.checking;
  readonly checkFailure = this.store.checkFailure;
  readonly hostKeyChanged = this.store.hostKeyChanged;
  readonly passphrase = this.store.passphrase;
  readonly deleting = this.store.deleting;

  readonly report = computed<CheckReportView | null>(() => {
    const server = this.server();
    if (!server || (server.last_check_status !== 'ok' && server.last_check_status !== 'problem')) {
      return null;
    }
    const report = server.last_check_report;
    const rows: readonly ReportRow[] = [
      valueRow('servers.check.report.system', report.system, 'notChecked'),
      valueRow('servers.check.report.dbsVersion', report.dbs_version, 'missing'),
      presenceRow('servers.check.report.backupCommand', report.backup_command),
      server.env_path
        ? presenceRow('servers.check.report.envFile', report.env_file)
        : { labelKey: 'servers.check.report.envFile', value: null, presence: 'notSet' },
      presenceRow('servers.check.report.remoteBackupDir', report.remote_backup_dir),
    ];
    const roots = server.file_roots.map((path) => ({ path, presence: presenceOf(report.roots?.[path]) }));
    return { rows, roots };
  });

  readonly settings = computed<readonly SettingRow[]>(() => {
    const server = this.server();
    return server ? settingRows(server) : [];
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.store.hidePassphrase());
  }

  look(presence: Presence): PresenceLook {
    return PRESENCE_LOOKS[presence];
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
      .open<Server, ServerFormData>(ServerForm, { titleKey: 'servers.form.editTitle', data: { server }, size: 'lg' })
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

  async togglePassphrase(): Promise<void> {
    if (this.passphrase()) {
      this.store.hidePassphrase();
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'servers.passphrase.prompt.title',
      bodyKey: 'servers.passphrase.prompt.body',
      submitKey: 'servers.passphrase.show',
      submit: (password) => this.store.revealPassphrase(password),
      error: this.store.revealError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  async copy(passphrase: string): Promise<void> {
    try {
      if (!this.clipboard) {
        throw new Error('No clipboard');
      }
      await this.clipboard.writeText(passphrase);
      this.notify('success', 'servers.passphrase.copied');
    } catch {
      this.notify('warning', 'servers.passphrase.copyUnavailable');
    }
  }

  async remove(): Promise<void> {
    const server = this.server();
    if (!server) {
      return;
    }
    const accepted = await this.confirmation.ask({
      // FSI and PDI keep the name in its own direction inside a title in either language.
      title: this.locale.translate('servers.delete.confirmTitle', { name: `\u2068${server.name}\u2069` }),
      message: this.locale.translate('servers.delete.confirmBody'),
      acceptLabel: this.locale.translate('servers.delete.action'),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: 'danger',
    });
    if (!accepted) {
      return;
    }
    if (await this.store.remove()) {
      this.notify('success', 'servers.delete.done');
      await this.router.navigate(['/servers']);
    } else {
      this.toaster.add({ severity: 'danger', summary: errorText(this.locale, this.store.deleteError()) });
    }
  }

  private notify(severity: ToastSeverity, key: string): void {
    this.toaster.add({ severity, summary: this.locale.translate(key) });
  }
}

function presenceOf(value: boolean | null | undefined): Presence {
  if (value === true) {
    return 'found';
  }
  return value === false ? 'missing' : 'notChecked';
}

function presenceRow(labelKey: string, value: boolean | null | undefined): ReportRow {
  return { labelKey, value: null, presence: presenceOf(value) };
}

function valueRow(labelKey: string, value: string | null | undefined, absent: Presence): ReportRow {
  return value ? { labelKey, value, presence: 'found' } : { labelKey, value: null, presence: absent };
}

function codeRow(labelKey: string, code: string): SettingRow {
  return code ? { labelKey, code } : { labelKey, textKey: 'servers.settings.notSet' };
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
    { labelKey: 'servers.settings.authMethod', textKey: `servers.authMethod.${server.auth_method}` },
    ...secrets,
    codeRow('servers.settings.projectDir', server.project_dir),
    codeRow('servers.settings.pythonPath', server.python_path),
    codeRow('servers.settings.managePath', server.manage_path),
    codeRow('servers.settings.settingsModule', server.settings_module),
    codeRow('servers.settings.remoteBackupDir', server.remote_backup_dir),
    codeRow('servers.settings.envPath', server.env_path),
  ];
}
