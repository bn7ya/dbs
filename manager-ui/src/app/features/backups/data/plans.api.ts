import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type { UnfinishedJob } from './backups.types';
import type { BackupPlan, PlanCreate, PlanListQuery, PlanUpdate, Reschedule } from './plans.types';

const UNFINISHED_RUNS_PAGE_SIZE = 100;

const RUN_ACTION = 'backup.run';

@Injectable({ providedIn: 'root' })
export class PlansApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/backups/plans';

  list(query: PlanListQuery): Observable<Page<BackupPlan>> {
    const params = new HttpParams()
      .set('application', query.application)
      .set('page', query.page)
      .set('page_size', query.page_size);
    return this.http.get<Page<BackupPlan>>(`${this.base}/`, { params });
  }

  create(plan: PlanCreate): Observable<BackupPlan> {
    return this.http.post<BackupPlan>(`${this.base}/`, plan);
  }

  update(id: string, changes: PlanUpdate): Observable<BackupPlan> {
    return this.http.patch<BackupPlan>(`${this.base}/${id}/`, changes);
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }

  run(id: string): Observable<JobStarted> {
    return this.http.post<JobStarted>(`${this.base}/${id}/run/`, {});
  }

  pause(id: string): Observable<BackupPlan> {
    return this.http.post<BackupPlan>(`${this.base}/${id}/pause/`, {});
  }

  resume(id: string): Observable<BackupPlan> {
    return this.http.post<BackupPlan>(`${this.base}/${id}/resume/`, {});
  }

  reschedule(id: string, moment: Reschedule): Observable<BackupPlan> {
    return this.http.post<BackupPlan>(`${this.base}/${id}/reschedule/`, moment);
  }

  unfinishedRuns(application: string, status: UnfinishedJob['status']): Observable<Page<UnfinishedJob>> {
    const params = new HttpParams()
      .set('application', application)
      .set('action', RUN_ACTION)
      .set('status', status)
      .set('page', 1)
      .set('page_size', UNFINISHED_RUNS_PAGE_SIZE);
    return this.http.get<Page<UnfinishedJob>>('/api/activity/', { params });
  }
}
