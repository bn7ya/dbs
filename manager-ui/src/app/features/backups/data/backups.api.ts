import { HttpClient, HttpEventType, HttpParams, type HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { filter, map, type Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type {
  ApplicationChoice,
  BackupFile,
  BackupListQuery,
  Dashboard,
  DownloadLink,
  RestoreRequest,
  UnfinishedJob,
  UploadEvent,
} from './backups.types';

const UNFINISHED_JOBS_PAGE_SIZE = 100;

// The most the backend serves in one page.
const APPLICATIONS_PAGE_SIZE = 200;

@Injectable({ providedIn: 'root' })
export class BackupsApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/backups';

  list(query: BackupListQuery): Observable<Page<BackupFile>> {
    let params = new HttpParams().set('page', query.page).set('page_size', query.page_size);
    if (query.application !== null) {
      params = params.set('application', query.application);
    }
    return this.http.get<Page<BackupFile>>(`${this.base}/`, { params });
  }

  take(application: string): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/take/`, { application });
  }

  downloadUrl(id: string): string {
    return `${this.base}/${id}/download/`;
  }

  downloadLink(id: string, accountPassword: string): Observable<DownloadLink> {
    return this.http.post<DownloadLink>(`${this.base}/${id}/download/`, { account_password: accountPassword });
  }

  verify(id: string): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/${id}/verify/`, {});
  }

  restore(id: string, request: RestoreRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/${id}/restore/`, request);
  }

  remove(id: string, accountPassword: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`, { body: { account_password: accountPassword } });
  }

  undoDelete(id: string): Observable<BackupFile> {
    return this.http.post<BackupFile>(`${this.base}/${id}/undo-delete/`, {});
  }

  // Bytes sent are reported by the XHR backend only (`withXhr()` in `app.config.ts`); fetch has no upload progress.
  upload(application: string, file: File): Observable<UploadEvent> {
    const body = new FormData();
    body.append('application', application);
    body.append('file', file);
    return this.http
      .post<BackupFile>(`${this.base}/upload/`, body, { reportProgress: true, observe: 'events' })
      .pipe(
        map((event) => uploadEventOf(event, file)),
        filter((event) => event !== null),
      );
  }

  applications(): Observable<Page<ApplicationChoice>> {
    const params = new HttpParams().set('page', 1).set('page_size', APPLICATIONS_PAGE_SIZE);
    return this.http.get<Page<ApplicationChoice>>('/api/applications/', { params });
  }

  storage(): Observable<Dashboard> {
    return this.http.get<Dashboard>('/api/dashboard/');
  }

  unfinishedJobs(application: string | null, status: UnfinishedJob['status']): Observable<Page<UnfinishedJob>> {
    let params = new HttpParams().set('status', status).set('page', 1).set('page_size', UNFINISHED_JOBS_PAGE_SIZE);
    if (application !== null) {
      params = params.set('application', application);
    }
    return this.http.get<Page<UnfinishedJob>>('/api/activity/', { params });
  }
}

function uploadEventOf(event: HttpEvent<BackupFile>, file: File): UploadEvent | null {
  switch (event.type) {
    case HttpEventType.UploadProgress:
      return { kind: 'progress', sent: event.loaded, total: event.total ?? file.size };
    case HttpEventType.Response:
      return event.body === null ? null : { kind: 'uploaded', file: event.body };
    default:
      return null;
  }
}
