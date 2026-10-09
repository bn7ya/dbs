import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { SetupRequest, SetupResult, SetupStatus } from './setup.types';

@Injectable({ providedIn: 'root' })
export class SetupApi {
  private readonly http = inject(HttpClient);
  private readonly url = '/api/setup/';

  status(): Observable<SetupStatus> {
    return this.http.get<SetupStatus>(this.url);
  }

  complete(request: SetupRequest): Observable<SetupResult> {
    return this.http.post<SetupResult>(this.url, request);
  }
}
