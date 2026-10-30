import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject } from '@angular/core';
import { Router } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';

import { Can } from '@core/auth/directives/can';
import type { ApiError } from '@core/http/api.types';
import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
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
import { ApplicationForm } from '../../components/application-form/application-form';
import type { ApplicationFormData } from '../../components/application-form/application-form.types';
import { CheckReport } from '../../components/check-report/check-report';
import { CheckTag } from '../../components/check-tag/check-tag';
import { DeploymentDialog } from '../../components/deployment-dialog/deployment-dialog';
import type { DeploymentDialogData } from '../../components/deployment-dialog/deployment-dialog.types';
import type { Application, DeploymentProfile } from '../../data/applications.types';
import { DEPLOYMENT_QUESTIONS, answerKey, answerOf, asks, merged } from '../../data/deployment';
import { ApplicationsStore } from '../../state/applications.store';
import type { DeploymentRow, SettingRow } from './application-overview.types';

@Component({
  selector: 'app-application-overview-page',
  imports: [
    Can,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatInput,
    AppDatePipe,
    CheckReport,
    CheckTag,
    CopyButton,
    Notice,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './application-overview.html',
  styleUrl: './application-overview.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationOverviewPage {
  private readonly store = inject(ApplicationsStore);
  private readonly dialogs = inject(Dialogs);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);

  readonly application = this.store.application;
  readonly versions = this.store.versions;
  readonly checking = this.store.checking;
  readonly checkFailure = this.store.checkFailure;
  readonly saving = this.store.saving;
  readonly passphrase = this.store.passphrase;
  readonly capturing = this.store.capturing;
  readonly captureError = this.store.captureError;
  readonly deleting = this.store.deleting;

  readonly reported = computed(() => {
    const status = this.application()?.last_check_status;
    return status === 'ok' || status === 'problem';
  });

  readonly settings = computed<readonly SettingRow[]>(() => {
    const application = this.application();
    return application ? settingRows(application) : [];
  });

  readonly deploymentRows = computed<readonly DeploymentRow[]>(() => {
    const application = this.application();
    return application ? deploymentRows(application.deployment, application.last_check_report.detected) : [];
  });

  readonly differs = computed(() => this.deploymentRows().some((row) => row.differs));

  readonly envInContainer = computed(() => {
    const application = this.application();
    return application !== undefined && application.kind !== 'host' && application.env_location === 'container';
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.store.hidePassphrase());
  }

  async check(): Promise<void> {
    if (await this.store.check()) {
      this.notify('success', 'applications.check.done');
    }
  }

  async useSuggestedPython(): Promise<void> {
    const suggestion = this.application()?.last_check_report.python_suggestion;
    if (!suggestion) {
      return;
    }
    if (await this.store.usePython(suggestion.python_path)) {
      this.notify('success', 'applications.check.done');
      return;
    }
    const failure = this.store.saveError();
    if (!asksForPassword(failure)) {
      if (failure) {
        this.toaster.add({ severity: 'danger', summary: errorText(this.locale, failure) });
      }
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'applications.overview.password.title',
      bodyKey: 'applications.overview.password.body',
      submitKey: 'applications.check.usePython',
      submit: (password) => this.store.usePython(suggestion.python_path, password),
      error: this.store.saveError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  async edit(): Promise<void> {
    const application = this.application();
    if (!application) {
      return;
    }
    const saved = await this.dialogs
      .open<Application, ApplicationFormData>(ApplicationForm, {
        titleKey: 'applications.form.editTitle',
        data: { application },
        size: 'lg',
      })
      .whenClosed();
    if (saved) {
      this.notify('success', 'applications.settings.updated');
    }
  }

  async editDeployment(): Promise<void> {
    const application = this.application();
    if (!application) {
      return;
    }
    const data: DeploymentDialogData = {
      profile: application.deployment,
      detected: application.last_check_report.detected ?? null,
      save: async (profile) => (await this.store.update({ deployment: profile })) !== null,
      error: this.store.saveError,
    };
    const saved = await this.dialogs
      .open<boolean, DeploymentDialogData>(DeploymentDialog, { titleKey: 'applications.deployment.title', data, size: 'md' })
      .whenClosed();
    if (saved) {
      this.notify('success', 'applications.deployment.saved');
    }
  }

  async useWhatWasFound(): Promise<void> {
    const application = this.application();
    if (!application) {
      return;
    }
    const profile = merged(application.deployment, application.last_check_report.detected);
    if (await this.store.update({ deployment: profile })) {
      this.notify('success', 'applications.deployment.saved');
    }
  }

  async togglePassphrase(): Promise<void> {
    if (this.passphrase()) {
      this.store.hidePassphrase();
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'applications.passphrase.prompt.title',
      bodyKey: 'applications.passphrase.prompt.body',
      submitKey: 'applications.passphrase.show',
      submit: (password) => this.store.revealPassphrase(password),
      error: this.store.revealError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  async capturePassphrase(): Promise<void> {
    if (await this.store.capturePassphrase()) {
      this.notify('success', 'applications.passphrase.captured');
    }
  }

  async remove(): Promise<void> {
    const application = this.application();
    if (!application) {
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'applications.delete.title',
      bodyKey: 'applications.delete.prompt',
      bodyValues: { name: isolated(application.name) },
      submitKey: 'applications.delete.action',
      destructive: true,
      submit: (password) => this.store.remove(password),
      error: this.store.deleteError,
    };
    const deleted = await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
    if (deleted) {
      this.notify('success', 'applications.delete.done');
      await this.router.navigate(['/servers', application.server.id, 'applications']);
    }
  }

  private notify(severity: ToastSeverity, key: string): void {
    this.toaster.add({ severity, summary: this.locale.translate(key) });
  }
}

function asksForPassword(error: ApiError | null): boolean {
  return (error?.fields?.['account_password'] ?? []).length > 0;
}

function deploymentRows(said: DeploymentProfile, found: DeploymentProfile | undefined): readonly DeploymentRow[] {
  const shown = merged(said, found);
  return DEPLOYMENT_QUESTIONS.filter((question) => asks(question.key, shown)).map((question) => {
    const answer = answerOf(said, question.key);
    const detected = answerOf(found, question.key);
    return {
      question: question.key,
      saidKey: answerKey(question.key, answer),
      foundKey: detected ? answerKey(question.key, detected) : '',
      differs: answer !== '' && detected !== '' && sameAnswer(question.key, answer) !== sameAnswer(question.key, detected),
    };
  });
}

function sameAnswer(question: string, value: string): string {
  return question === 'database' && value === 'mariadb' ? 'mysql' : value;
}

function codeRow(labelKey: string, code: string): SettingRow {
  return code ? { labelKey, code } : { labelKey, textKey: 'applications.settings.notSet' };
}

function settingRows(application: Application): readonly SettingRow[] {
  const contained = application.kind !== 'host';
  const engine: readonly SettingRow[] = contained
    ? [{ labelKey: 'applications.settings.engine', textKey: `applications.engine.${application.engine || 'none'}` }]
    : [];
  const compose: readonly SettingRow[] =
    application.kind === 'compose'
      ? [
          codeRow('applications.settings.composeProject', application.compose_project),
          codeRow('applications.settings.composeService', application.compose_service),
          application.compose_files.length > 0
            ? codeRow('applications.settings.composeFiles', application.compose_files.join(' '))
            : { labelKey: 'applications.settings.composeFiles', textKey: 'applications.settings.composeDefault' },
        ]
      : [];
  const container: readonly SettingRow[] =
    application.kind === 'container' ? [codeRow('applications.settings.containerName', application.container_name)] : [];
  const workdir: readonly SettingRow[] = contained ? [codeRow('applications.settings.workdir', application.workdir)] : [];
  const envLocation: readonly SettingRow[] =
    contained && application.env_path
      ? [{ labelKey: 'applications.settings.envLocation', textKey: `applications.envLocation.${application.env_location}` }]
      : [];
  return [
    { labelKey: 'applications.settings.kind', textKey: `applications.kind.${application.kind}` },
    ...engine,
    ...compose,
    ...container,
    codeRow('applications.settings.projectDir', application.project_dir),
    ...workdir,
    codeRow('applications.settings.pythonPath', application.python_path),
    codeRow('applications.settings.managePath', application.manage_path),
    codeRow('applications.settings.settingsModule', application.settings_module),
    codeRow('applications.settings.remoteBackupDir', application.remote_backup_dir),
    codeRow('applications.settings.envPath', application.env_path),
    ...envLocation,
  ];
}
