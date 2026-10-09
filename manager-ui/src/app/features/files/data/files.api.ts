import { HttpClient, HttpEventType, HttpParams, type HttpEvent } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { filter, map, type Observable } from 'rxjs';

import type { Entry, Listing, ListingQuery, NewFolder, UploadEvent } from './files.types';

@Injectable({ providedIn: 'root' })
export class FilesApi {
  private readonly http = inject(HttpClient);

  list(query: ListingQuery): Observable<Listing> {
    let params = new HttpParams().set('page', query.page).set('page_size', query.page_size);
    if (query.path !== null) {
      params = params.set('path', query.path);
    }
    return this.http.get<Listing>(this.base(query.server), { params });
  }

  downloadUrl(server: string, path: string): string {
    return `${this.base(server)}download/?path=${encodeURIComponent(path)}`;
  }

  // Bytes sent are reported by the XHR backend only (`withXhr()` in `app.config.ts`); fetch has no upload progress.
  upload(server: string, folder: string, file: File): Observable<UploadEvent> {
    const body = new FormData();
    body.append('path', folder);
    body.append('file', file);
    return this.http
      .post<Entry>(`${this.base(server)}upload/`, body, { reportProgress: true, observe: 'events' })
      .pipe(
        map((event) => uploadEventOf(event, file)),
        filter((event) => event !== null),
      );
  }

  createFolder(server: string, folder: NewFolder): Observable<Entry> {
    return this.http.post<Entry>(`${this.base(server)}folders/`, folder);
  }

  remove(server: string, path: string): Observable<void> {
    return this.http.delete<void>(this.base(server), { params: new HttpParams().set('path', path) });
  }

  private base(server: string): string {
    return `/api/files/${server}/`;
  }
}

function uploadEventOf(event: HttpEvent<Entry>, file: File): UploadEvent | null {
  switch (event.type) {
    case HttpEventType.UploadProgress:
      return { kind: 'progress', sent: event.loaded, total: event.total ?? file.size };
    case HttpEventType.Response:
      return event.body === null ? null : { kind: 'uploaded', entry: event.body };
    default:
      return null;
  }
}
