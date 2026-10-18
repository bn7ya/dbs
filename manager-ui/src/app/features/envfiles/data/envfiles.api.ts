import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { map, type Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type {
  EnvComparison,
  EnvListQuery,
  EnvPlace,
  EnvVersion,
  PullResult,
  PushResult,
  RevealedEnv,
} from './envfiles.types';

@Injectable({ providedIn: 'root' })
export class EnvfilesApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/envfiles';

  list(query: EnvListQuery): Observable<Page<EnvVersion>> {
    const params = new HttpParams()
      .set('application', query.application)
      .set('page', query.page)
      .set('page_size', query.page_size);
    return this.http.get<Page<EnvVersion>>(`${this.base}/`, { params });
  }

  pull(application: string): Observable<PullResult> {
    return this.http.post<PullResult>(`${this.base}/pull/`, { application });
  }

  compare(from: string, to: string): Observable<EnvComparison> {
    return this.http.get<EnvComparison>(`${this.base}/${from}/compare/`, { params: new HttpParams().set('to', to) });
  }

  reveal(id: string, password: string): Observable<RevealedEnv> {
    return this.http.post<RevealedEnv>(`${this.base}/${id}/reveal/`, { password });
  }

  push(id: string, password: string): Observable<PushResult> {
    return this.http.post<PushResult>(`${this.base}/${id}/push/`, { password });
  }

  place(application: string): Observable<EnvPlace> {
    return this.http
      .get<EnvPlace>(`/api/applications/${application}/`)
      .pipe(map(({ env_path, env_location }) => ({ env_path, env_location })));
  }
}
