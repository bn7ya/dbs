import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import type { Observable } from 'rxjs';

import type { Page } from '@core/http/api.types';
import type {
  CreatedServer,
  HostKey,
  HostKeyConfirmation,
  HostKeyDecision,
  HostKeyRepin,
  HostKeyTarget,
  PublicKey,
  Server,
  ServerCreate,
  ServerListQuery,
  ServerMerge,
  ServerSummary,
  ServerUpdate,
} from './servers.types';

const HOST_KEYS_PAGE_SIZE = 100;

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

  get(id: string): Observable<Server> {
    return this.http.get<Server>(`${this.base}/${id}/`);
  }

  update(id: string, changes: ServerUpdate): Observable<Server> {
    return this.http.patch<Server>(`${this.base}/${id}/`, changes);
  }

  remove(id: string, accountPassword: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`, { body: { account_password: accountPassword } });
  }

  check(id: string): Observable<Server> {
    return this.http.post<Server>(`${this.base}/${id}/check/`, {});
  }

  merge(id: string, merge: ServerMerge): Observable<Server> {
    return this.http.post<Server>(`${this.base}/${id}/merge/`, merge);
  }

  fingerprint(target: HostKeyTarget): Observable<HostKey> {
    return this.http.post<HostKey>(`${this.base}/fingerprint/`, target);
  }

  hostKeyConfirmations(): Observable<Page<HostKeyConfirmation>> {
    const params = new HttpParams().set('page', 1).set('page_size', HOST_KEYS_PAGE_SIZE);
    return this.http.get<Page<HostKeyConfirmation>>(`${this.base}/host-keys/`, { params });
  }

  decideHostKey(id: string, decision: HostKeyDecision): Observable<HostKeyConfirmation> {
    return this.http.post<HostKeyConfirmation>(`${this.base}/host-keys/${id}/${decision}/`, {});
  }

  publicKey(id: string): Observable<PublicKey> {
    return this.http.get<PublicKey>(`${this.base}/${id}/public-key/`);
  }

  repinHostKey(id: string, repin: HostKeyRepin): Observable<Server> {
    return this.http.post<Server>(`${this.base}/${id}/host-key/`, repin);
  }
}
