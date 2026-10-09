import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { map, type Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type {
  EnvComparison,
  EnvListQuery,
  EnvVersion,
  PullResult,
  PushResult,
  RevealedEnv,
  ServerEnvPath,
} from './envfiles.types';

@Injectable({ providedIn: 'root' })
export class EnvfilesApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/envfiles';

  list(query: EnvListQuery): Observable<Page<EnvVersion>> {
    const params = new HttpParams()
      .set('server', query.server)
      .set('page', query.page)
      .set('page_size', query.page_size);
    return this.http.get<Page<EnvVersion>>(`${this.base}/`, { params });
  }

  pull(server: string): Observable<PullResult> {
    return this.http.post<PullResult>(`${this.base}/pull/`, { server });
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

  envPath(server: string): Observable<string> {
    return this.http.get<ServerEnvPath>(`/api/servers/${server}/`).pipe(map((found) => found.env_path));
  }
}
