import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { About } from './about.types';

@Injectable({ providedIn: 'root' })
export class AboutApi {
  private readonly http = inject(HttpClient);

  get(): Observable<About> {
    return this.http.get<About>('/api/about/');
  }
}
