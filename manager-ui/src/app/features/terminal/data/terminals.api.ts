import { HttpClient, HttpParams } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { map, type Observable } from 'rxjs';

import type { TerminalSize } from '@shared/terminal-view/terminal-view.types';
import type {
  Terminal,
  TerminalApplication,
  TerminalInputAnswer,
  TerminalList,
  TerminalOpening,
  TerminalOutput,
  TerminalOutputAnswer,
  TerminalServer,
} from './terminals.types';

@Injectable({ providedIn: 'root' })
export class TerminalsApi {
  private readonly http = inject(HttpClient);
  private readonly base = '/api/terminals';

  list(): Observable<readonly Terminal[]> {
    return this.http.get<TerminalList>(`${this.base}/`).pipe(map((list) => list.results));
  }

  open(opening: TerminalOpening): Observable<Terminal> {
    return this.http.post<Terminal>(`${this.base}/`, opening);
  }

  output(id: string, cursor: number): Observable<TerminalOutput> {
    const params = new HttpParams().set('cursor', cursor);
    return this.http.get<TerminalOutputAnswer>(`${this.base}/${id}/output/`, { params }).pipe(map(decoded));
  }

  input(id: string, seq: number, data: string): Observable<TerminalInputAnswer> {
    return this.http.post<TerminalInputAnswer>(`${this.base}/${id}/input/`, { seq, data });
  }

  resize(id: string, size: TerminalSize): Observable<Terminal> {
    return this.http.post<Terminal>(`${this.base}/${id}/resize/`, { cols: size.cols, rows: size.rows });
  }

  close(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/${id}/`);
  }

  server(id: string): Observable<TerminalServer> {
    return this.http.get<TerminalServer>(`/api/servers/${id}/`);
  }

  application(id: string): Observable<TerminalApplication> {
    return this.http.get<TerminalApplication>(`/api/applications/${id}/`);
  }
}

function decoded(answer: TerminalOutputAnswer): TerminalOutput {
  return {
    bytes: bytesOf(answer.data),
    cursor: answer.cursor,
    skipped: answer.skipped,
    closed: answer.closed,
    reason: answer.reason === '' ? null : answer.reason,
    exitStatus: answer.exit_status,
  };
}

function bytesOf(base64: string): Uint8Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}
