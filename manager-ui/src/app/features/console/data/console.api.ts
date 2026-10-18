import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { ConsoleRequest, ConsoleResult } from './console.types';

@Injectable({ providedIn: 'root' })
export class ConsoleApi {
  private readonly http = inject(HttpClient);

  run(request: ConsoleRequest): Observable<ConsoleResult> {
    return this.http.post<ConsoleResult>('/api/console/', request);
  }
}
