import { HttpClient, HttpEventType, HttpParams, type HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { filter, map, type Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type {
  BackupFile,
  BackupListQuery,
  BackupPlan,
  PlanCreate,
  PlanListQuery,
  PlanUpdate,
  RestoreRequest,
  TargetServer,
  UnfinishedJob,
  UploadEvent,
} from './backups.types';

const UNFINISHED_JOBS_PAGE_SIZE = 100;

const TARGET_SERVERS_PAGE_SIZE = 100;

@Injectable({ providedIn: 'root' })
export class BackupsApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/backups';

  list(query: BackupListQuery): Observable<Page<BackupFile>> {
    const params = new HttpParams()
      .set('server', query.server)
      .set('page', query.page)
      .set('page_size', query.page_size);
    return this.http.get<Page<BackupFile>>(`${this.base}/`, { params });
  }

  take(server: string): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/take/`, { server });
  }

  downloadUrl(id: string): string {
    return `${this.base}/${id}/download/`;
  }

  verify(id: string): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/${id}/verify/`, {});
  }

  restore(id: string, request: RestoreRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/${id}/restore/`, request);
  }

  targetServers(): Observable<Page<TargetServer>> {
    const params = new HttpParams().set('page', 1).set('page_size', TARGET_SERVERS_PAGE_SIZE);
    return this.http.get<Page<TargetServer>>('/api/servers/', { params });
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }

  undoDelete(id: string): Observable<BackupFile> {
    return this.http.post<BackupFile>(`${this.base}/${id}/undo-delete/`, {});
  }

  // Bytes sent are reported by the XHR backend only (`withXhr()` in `app.config.ts`); fetch has no upload progress.
  upload(server: string, file: File): Observable<UploadEvent> {
    const body = new FormData();
    body.append('server', server);
    body.append('file', file);
    return this.http
      .post<BackupFile>(`${this.base}/upload/`, body, { reportProgress: true, observe: 'events' })
      .pipe(
        map((event) => uploadEventOf(event, file)),
        filter((event) => event !== null),
      );
  }

  plans(query: PlanListQuery): Observable<Page<BackupPlan>> {
    const params = new HttpParams()
      .set('server', query.server)
      .set('page', query.page)
      .set('page_size', query.page_size);
    return this.http.get<Page<BackupPlan>>(`${this.base}/plans/`, { params });
  }

  createPlan(plan: PlanCreate): Observable<BackupPlan> {
    return this.http.post<BackupPlan>(`${this.base}/plans/`, plan);
  }

  updatePlan(id: string, changes: PlanUpdate): Observable<BackupPlan> {
    return this.http.patch<BackupPlan>(`${this.base}/plans/${id}/`, changes);
  }

  removePlan(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/plans/${id}/`);
  }

  runPlan(id: string): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/plans/${id}/run/`, {});
  }

  unfinishedJobs(server: string, status: UnfinishedJob['status']): Observable<Page<UnfinishedJob>> {
    const params = new HttpParams()
      .set('server', server)
      .set('status', status)
      .set('page', 1)
      .set('page_size', UNFINISHED_JOBS_PAGE_SIZE);
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
