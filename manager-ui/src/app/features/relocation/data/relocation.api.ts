import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type { MoveApplication, MoveServer, ServerMoveRequest } from './relocation.types';

const LIST_SIZE = 100;

@Injectable({ providedIn: 'root' })
export class RelocationApi {
  private readonly http = inject(HttpClient);

  server(id: string): Observable<MoveServer> {
    return this.http.get<MoveServer>(`/api/servers/${id}/`);
  }

  servers(): Observable<Page<MoveServer>> {
    const params = new HttpParams().set('page', 1).set('page_size', LIST_SIZE);
    return this.http.get<Page<MoveServer>>('/api/servers/', { params });
  }

  applications(server: string): Observable<Page<MoveApplication>> {
    const params = new HttpParams().set('server', server).set('page', 1).set('page_size', LIST_SIZE);
    return this.http.get<Page<MoveApplication>>('/api/applications/', { params });
  }

  move(server: string, request: ServerMoveRequest): Observable<JobStarted> {
    return this.http.post<JobStarted>(`/api/servers/${server}/move/`, request);
  }
}
