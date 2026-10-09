import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Job } from './job.types';

@Injectable({ providedIn: 'root' })
export class JobsApi {
  private readonly http = inject(HttpClient);

  get(id: string): Observable<Job> {
    return this.http.get<Job>(`/api/activity/${id}/`);
  }
}
