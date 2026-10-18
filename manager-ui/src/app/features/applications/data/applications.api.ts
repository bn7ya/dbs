import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type {
  Application,
  ApplicationCreate,
  ApplicationListQuery,
  ApplicationSummary,
  ApplicationUpdate,
  BackupPassphrase,
  BrowseQuery,
  CheckedApplication,
  DiscoverRequest,
  Discovery,
  HostServer,
  PassphraseCapture,
  RemoteFolder,
} from './applications.types';

@Injectable({ providedIn: 'root' })
export class ApplicationsApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/applications';

  list(query: ApplicationListQuery): Observable<Page<ApplicationSummary>> {
    let params = new HttpParams().set('page', query.page).set('page_size', query.page_size);
    if (query.search) {
      params = params.set('search', query.search);
    }
    if (query.server) {
      params = params.set('server', query.server);
    }
    return this.http.get<Page<ApplicationSummary>>(`${this.base}/`, { params });
  }

  create(application: ApplicationCreate): Observable<Application> {
    return this.http.post<Application>(`${this.base}/`, application);
  }

  get(id: string): Observable<Application> {
    return this.http.get<Application>(`${this.base}/${id}/`);
  }

  update(id: string, changes: ApplicationUpdate): Observable<Application> {
    return this.http.patch<Application>(`${this.base}/${id}/`, changes);
  }

  remove(id: string, accountPassword: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`, { body: { account_password: accountPassword } });
  }

  discover(request: DiscoverRequest): Observable<Discovery> {
    return this.http.post<Discovery>(`${this.base}/discover/`, request);
  }

  check(id: string): Observable<CheckedApplication> {
    return this.http.post<CheckedApplication>(`${this.base}/${id}/check/`, {});
  }

  revealPassphrase(id: string, password: string): Observable<BackupPassphrase> {
    return this.http.post<BackupPassphrase>(`${this.base}/${id}/passphrase/`, { password });
  }

  capturePassphrase(id: string): Observable<PassphraseCapture> {
    return this.http.post<PassphraseCapture>(`${this.base}/${id}/passphrase/capture/`, {});
  }

  takeBackup(application: string): Observable<JobStarted> {
    return this.http.post<JobStarted>('/api/backups/take/', { application });
  }

  server(id: string): Observable<HostServer> {
    return this.http.get<HostServer>(`/api/servers/${id}/`);
  }

  browse(query: BrowseQuery): Observable<RemoteFolder> {
    let params = new HttpParams().set('page', query.page).set('page_size', query.page_size);
    if (query.path !== null) {
      params = params.set('path', query.path);
    }
    return this.http.get<RemoteFolder>(`/api/servers/${query.server}/browse/`, { params });
  }
}
