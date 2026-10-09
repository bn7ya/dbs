import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { ActivityEntry, ActivityQuery } from './activity.types';

@Injectable({ providedIn: 'root' })
export class ActivityApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/activity';

  list(query: ActivityQuery): Observable<Page<ActivityEntry>> {
    let params = new HttpParams().set('page', query.page).set('page_size', query.page_size);
    if (query.server) {
      params = params.set('server', query.server);
    }
    if (query.action) {
      params = params.set('action', query.action);
    }
    if (query.status) {
      params = params.set('status', query.status);
    }
    return this.http.get<Page<ActivityEntry>>(`${this.base}/`, { params });
  }
}
