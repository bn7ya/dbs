import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { map, type Observable } from 'rxjs';

import { CsrfToken } from '@core/http/csrf-token';
import type {
  Credentials,
  CsrfAnswer,
  Enrollment,
  Identity,
  PasswordChange,
  RecoveryCodes,
  SecondFactor,
  SignedIn,
  SignInStep,
} from './auth.types';

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);
  private readonly csrf = inject(CsrfToken);
  private readonly base = '/api/auth';

  primeCsrf(): Observable<void> {
    return this.http
      .get<CsrfAnswer>(`${this.base}/csrf/`)
      .pipe(map((answer) => this.csrf.hold(answer.csrf_token)));
  }

  signIn(credentials: Credentials): Observable<SignInStep> {
    return this.http.post<SignInStep>(`${this.base}/login/`, credentials);
  }

  secondFactor(factor: SecondFactor): Observable<Identity> {
    return this.http.post<Identity>(`${this.base}/two-factor/`, factor);
  }

  enrollment(): Observable<Enrollment> {
    return this.http.post<Enrollment>(`${this.base}/two-factor/enrollment/`, {});
  }

  enroll(code: string): Observable<SignedIn> {
    return this.http.post<SignedIn>(`${this.base}/two-factor/enrollment/confirm/`, { code });
  }

  changePassword(change: PasswordChange): Observable<Identity> {
    return this.http.post<Identity>(`${this.base}/password/`, change);
  }

  newRecoveryCodes(password: string): Observable<RecoveryCodes> {
    return this.http.post<RecoveryCodes>(`${this.base}/recovery-codes/`, { password });
  }

  signOut(): Observable<void> {
    return this.http.post<void>(`${this.base}/logout/`, {});
  }

  me(): Observable<Identity> {
    return this.http.get<Identity>(`${this.base}/me/`);
  }
}
