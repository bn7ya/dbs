import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import {
  REDEPLOY_LIST_SIZE,
  type RedeployBackup,
  type RedeployEnvVersion,
  type RedeployRequest,
  type RedeployServer,
} from './redeploy.types';

@Injectable({ providedIn: 'root' })
export class RedeployApi {
  private readonly http = inject(HttpClient);

  servers(): Observable<Page<RedeployServer>> {
    return this.http.get<Page<RedeployServer>>('/api/servers/', { params: firstPage() });
  }

  backups(server: string): Observable<Page<RedeployBackup>> {
    return this.http.get<Page<RedeployBackup>>('/api/backups/', { params: firstPage().set('server', server) });
  }

  envVersions(server: string): Observable<Page<RedeployEnvVersion>> {
    return this.http.get<Page<RedeployEnvVersion>>('/api/envfiles/', { params: firstPage().set('server', server) });
  }

  run(request: RedeployRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>('/api/redeploy/', request);
  }
}

function firstPage(): HttpParams {
  return new HttpParams().set('page', 1).set('page_size', REDEPLOY_LIST_SIZE);
}
