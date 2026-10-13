import { Injectable, computed, inject, signal } from '@angular/core';
import { firstValueFrom, type Observable } from 'rxjs';

import type { ApiError } from '@core/http/api.types';
import { AccountsApi } from '../data/accounts.api';
import type { Account, AccountCreate, AssignableRole, HandOver } from '../data/accounts.types';

@Injectable()
export class AccountsStore {
  private readonly api = inject(AccountsApi);

  private readonly rows = signal<readonly Account[]>([]);

  readonly accounts = this.rows.asReadonly();
  readonly loaded = signal(false);
  readonly loading = signal(false);
  readonly error = signal<ApiError | null>(null);
  readonly busy = signal(false);
  readonly formError = signal<ApiError | null>(null);

  readonly pending = computed(() => this.loading() && !this.loaded());

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      this.rows.set(await firstValueFrom(this.api.list()));
      this.loaded.set(true);
    } catch (error) {
      this.error.set(error as ApiError);
    } finally {
      this.loading.set(false);
    }
  }

  resetForm(): void {
    this.formError.set(null);
  }

  create(body: AccountCreate): Promise<boolean> {
    return this.change(this.api.create(body), (created) => [...this.rows(), created]);
  }

  setRole(account: Account, role: AssignableRole): Promise<boolean> {
    return this.replace(this.api.update(account.id, { role }));
  }

  setActive(account: Account, active: boolean): Promise<boolean> {
    return this.replace(this.api.update(account.id, { is_active: active }));
  }

  resetTwoFactor(account: Account): Promise<boolean> {
    return this.replace(this.api.resetTwoFactor(account.id));
  }

  expirePassword(account: Account): Promise<boolean> {
    return this.replace(this.api.expirePassword(account.id));
  }

  handOver(account: Account, body: HandOver): Promise<boolean> {
    return this.replace(this.api.handOver(account.id, body));
  }

  private replace(request: Observable<Account>): Promise<boolean> {
    return this.change(request, (changed) =>
      this.rows().map((row) => (row.id === changed.id ? changed : row)),
    );
  }

  private async change(
    request: Observable<Account>,
    next: (changed: Account) => readonly Account[],
  ): Promise<boolean> {
    this.busy.set(true);
    this.formError.set(null);
    try {
      this.rows.set(next(await firstValueFrom(request)));
      return true;
    } catch (error) {
      this.formError.set(error as ApiError);
      return false;
    } finally {
      this.busy.set(false);
    }
  }
}
