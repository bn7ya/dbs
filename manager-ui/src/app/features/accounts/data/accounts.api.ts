import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Account, AccountCreate, AccountUpdate, HandOver } from './accounts.types';

@Injectable({ providedIn: 'root' })
export class AccountsApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/accounts';

  list(): Observable<Account[]> {
    return this.http.get<Account[]>(`${this.base}/`);
  }

  create(body: AccountCreate): Observable<Account> {
    return this.http.post<Account>(`${this.base}/`, body);
  }

  update(id: number, changes: AccountUpdate): Observable<Account> {
    return this.http.patch<Account>(`${this.base}/${id}/`, changes);
  }

  resetTwoFactor(id: number): Observable<Account> {
    return this.http.post<Account>(`${this.base}/${id}/two-factor/reset/`, {});
  }

  expirePassword(id: number): Observable<Account> {
    return this.http.post<Account>(`${this.base}/${id}/password/expire/`, {});
  }

  handOver(id: number, body: HandOver): Observable<Account> {
    return this.http.post<Account>(`${this.base}/${id}/master/`, body);
  }
}
