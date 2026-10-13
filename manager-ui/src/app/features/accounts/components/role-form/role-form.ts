import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButton } from '@angular/material/button';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogData, injectDialogRef } from '@shared/dialogs/dialogs';
import { isolated } from '@shared/isolated/isolated';
import { Notice } from '@shared/notice/notice';
import type { AssignableRole } from '../../data/accounts.types';
import { AccountsStore } from '../../state/accounts.store';
import { RoleChoice } from '../role-choice/role-choice';
import type { AccountDialogData } from './role-form.types';

@Component({
  selector: 'app-role-form',
  imports: [MatButton, Notice, RoleChoice, ErrorTextPipe, TranslatePipe],
  templateUrl: './role-form.html',
  styleUrl: './role-form.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RoleForm {
  private readonly store = inject(AccountsStore);
  private readonly ref = injectDialogRef<boolean>();

  readonly account = injectDialogData<AccountDialogData>().account;
  readonly name = isolated(this.account.username);
  readonly role = signal<AssignableRole>(this.account.role === 'master' ? 'admin' : this.account.role);
  readonly busy = this.store.busy;
  readonly failure = this.store.formError;

  constructor() {
    this.store.resetForm();
  }

  cancel(): void {
    this.ref.close();
  }

  async submit(): Promise<void> {
    if (await this.store.setRole(this.account, this.role())) {
      this.ref.close(true);
    }
  }
}
