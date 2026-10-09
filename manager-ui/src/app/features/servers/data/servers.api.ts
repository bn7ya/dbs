import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type { JobStarted } from '@core/jobs/job.types';
import type {
  BackupPassphrase,
  CheckedServer,
  CreatedServer,
  Discovery,
  PassphraseCapture,
  PublicKey,
  HostKey,
  HostKeyRepin,
  HostKeyTarget,
  Server,
  ServerCreate,
  ServerListQuery,
  ServerSummary,
  ServerUpdate,
} from './servers.types';

@Injectable({ providedIn: 'root' })
export class ServersApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/servers';

  list(query: ServerListQuery): Observable<Page<ServerSummary>> {
    let params = new HttpParams().set('page', query.page).set('page_size', query.page_size);
    if (query.search) {
      params = params.set('search', query.search);
    }
    return this.http.get<Page<ServerSummary>>(`${this.base}/`, { params });
  }

  create(server: ServerCreate): Observable<CreatedServer> {
    return this.http.post<CreatedServer>(`${this.base}/`, server);
  }

  publicKey(id: string): Observable<PublicKey> {
    return this.http.get<PublicKey>(`${this.base}/${id}/public-key/`);
  }

  discover(id: string): Observable<Discovery> {
    return this.http.post<Discovery>(`${this.base}/${id}/discover/`, {});
  }

  capturePassphrase(id: string): Observable<PassphraseCapture> {
    return this.http.post<PassphraseCapture>(`${this.base}/${id}/passphrase/capture/`, {});
  }

  takeBackup(server: string): Observable<JobStarted> {
    return this.http.post<JobStarted>('/api/backups/take/', { server });
  }

  get(id: string): Observable<Server> {
    return this.http.get<Server>(`${this.base}/${id}/`);
  }

  update(id: string, changes: ServerUpdate): Observable<Server> {
    return this.http.patch<Server>(`${this.base}/${id}/`, changes);
  }

  remove(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }

  fingerprint(target: HostKeyTarget): Observable<HostKey> {
    return this.http.post<HostKey>(`${this.base}/fingerprint/`, target);
  }

  check(id: string): Observable<CheckedServer> {
    return this.http.post<CheckedServer>(`${this.base}/${id}/check/`, {});
  }

  repinHostKey(id: string, repin: HostKeyRepin): Observable<Server> {
    return this.http.post<Server>(`${this.base}/${id}/host-key/`, repin);
  }

  revealPassphrase(id: string, password: string): Observable<BackupPassphrase> {
    return this.http.post<BackupPassphrase>(`${this.base}/${id}/passphrase/`, { password });
  }
}
