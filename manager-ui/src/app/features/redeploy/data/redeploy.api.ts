import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type {
  DeployApplication,
  DeployStepsRequest,
  MoveRequest,
  RedeployApplication,
  RedeployBackup,
  RedeployEnvVersion,
  RunRequest,
} from './redeploy.types';

const REDEPLOY_LIST_SIZE = 100;

@Injectable({ providedIn: 'root' })
export class RedeployApi {
  private readonly http = inject(HttpClient);

  application(id: string): Observable<DeployApplication> {
    return this.http.get<DeployApplication>(`/api/applications/${id}/`);
  }

  applications(): Observable<Page<RedeployApplication>> {
    return this.http.get<Page<RedeployApplication>>('/api/applications/', { params: firstPage() });
  }

  backups(application: string): Observable<Page<RedeployBackup>> {
    return this.http.get<Page<RedeployBackup>>('/api/backups/', {
      params: firstPage().set('application', application),
    });
  }

  envVersions(application: string): Observable<Page<RedeployEnvVersion>> {
    return this.http.get<Page<RedeployEnvVersion>>('/api/envfiles/', {
      params: firstPage().set('application', application),
    });
  }

  saveSteps(application: string, request: DeployStepsRequest): Observable<DeployApplication> {
    return this.http.put<DeployApplication>(`/api/applications/${application}/deploy-steps/`, request);
  }

  deploy(application: string, request: RunRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>(`/api/applications/${application}/deploy/`, request);
  }

  move(request: MoveRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>('/api/redeploy/', request);
  }

  revert(job: number, request: RunRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>(`/api/redeploy/${job}/revert/`, request);
  }
}

function firstPage(): HttpParams {
  return new HttpParams().set('page', 1).set('page_size', REDEPLOY_LIST_SIZE);
}
