import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton, MatIconButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatMenu, MatMenuItem, MatMenuTrigger } from '@angular/material/menu';
import { MatTableModule } from '@angular/material/table';
import { Router } from '@angular/router';

import { AuthStore } from '@core/auth/state/auth.store';
import { ErrorTextPipe, errorText } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import { Toaster } from '@shared/toaster/toaster';
import { AccountForm } from '../../components/account-form/account-form';
import { HandOverForm } from '../../components/hand-over-form/hand-over-form';
import { RoleForm } from '../../components/role-form/role-form';
import type { AccountDialogData } from '../../components/role-form/role-form.types';
import type { Account } from '../../data/accounts.types';
import { AccountsStore } from '../../state/accounts.store';
import type { AccountAction } from './accounts.types';

const COLUMNS = ['username', 'role', 'status', 'twoFactor', 'password', 'lastLogin', 'actions'];

@Component({
  selector: 'app-accounts-page',
  imports: [
    MatButton,
    MatIconButton,
    MatCard,
    MatCardContent,
    MatMenu,
    MatMenuItem,
    MatMenuTrigger,
    MatTableModule,
    Notice,
    Skeleton,
    StatusTag,
    AppDatePipe,
    ErrorTextPipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './accounts.html',
  styleUrl: './accounts.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AccountsPage {
  private readonly store = inject(AccountsStore);
  private readonly auth = inject(AuthStore);
  private readonly dialogs = inject(Dialogs);
  private readonly confirmation = inject(Confirmation);
  private readonly toaster = inject(Toaster);
  private readonly locale = inject(LocaleStore);
  private readonly router = inject(Router);

  readonly accounts = this.store.accounts;
  readonly pending = this.store.pending;
  readonly loading = this.store.loading;
  readonly error = this.store.error;
  readonly columns = COLUMNS;
  readonly skeletonLines = [1, 2, 3];

  constructor() {
    void this.store.load();
  }

  retry(): void {
    void this.store.load();
  }

  async add(): Promise<void> {
    const added = await this.dialogs.open<boolean>(AccountForm, { titleKey: 'accounts.form.title' }).whenClosed();
    if (added) {
      this.toaster.add({ severity: 'success', summary: this.locale.translate('accounts.form.done') });
    }
  }

  async changeRole(account: Account): Promise<void> {
    const changed = await this.dialogs
      .open<boolean, AccountDialogData>(RoleForm, { titleKey: 'accounts.roleForm.title', size: 'sm', data: { account } })
      .whenClosed();
    if (changed) {
      this.done('accounts.roleForm.done', account);
    }
  }

  async handOver(account: Account): Promise<void> {
    const handed = await this.dialogs
      .open<boolean, AccountDialogData>(HandOverForm, {
        titleKey: 'accounts.handOver.title',
        size: 'sm',
        data: { account },
      })
      .whenClosed();
    if (handed) {
      this.done('accounts.handOver.done', account);
      await this.auth.restore();
      await this.router.navigateByUrl('/');
    }
  }

  async act(action: AccountAction, account: Account): Promise<void> {
    const name = isolated(account.username);
    const confirmed = await this.confirmation.ask({
      title: this.locale.translate(`accounts.${action}.title`),
      message: this.locale.translate(`accounts.${action}.body`, { name }),
      acceptLabel: this.locale.translate(`accounts.${action}.accept`),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: action === 'disable' || action === 'resetTwoFactor' ? 'danger' : 'primary',
    });
    if (!confirmed) {
      return;
    }
    const finished = await this.perform(action, account);
    if (finished) {
      this.done(`accounts.${action}.done`, account);
    } else {
      this.toaster.add({ severity: 'danger', summary: errorText(this.locale, this.store.formError()) });
    }
  }

  isMaster(account: Account): boolean {
    return account.role === 'master';
  }

  isSelf(account: Account): boolean {
    return account.id === this.auth.user()?.id;
  }

  private perform(action: AccountAction, account: Account): Promise<boolean> {
    switch (action) {
      case 'disable':
        return this.store.setActive(account, false);
      case 'enable':
        return this.store.setActive(account, true);
      case 'resetTwoFactor':
        return this.store.resetTwoFactor(account);
      case 'expirePassword':
        return this.store.expirePassword(account);
    }
  }

  private done(key: string, account: Account): void {
    this.toaster.add({
      severity: 'success',
      summary: this.locale.translate(key, { name: isolated(account.username) }),
    });
  }
}
