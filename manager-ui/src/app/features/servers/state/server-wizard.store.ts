import { Injectable, inject, signal, type WritableSignal } from '@angular/core';
import { firstValueFrom, type Observable } from 'rxjs';

import type { ApiError } from '@core/http/api.types';
import { ServersApi } from '../data/servers.api';
import type { CreatedServer, HostKey, HostKeyTarget, Server, ServerCreate } from '../data/servers.types';

@Injectable()
export class ServerWizardStore {
  private readonly api = inject(ServersApi);

  readonly server = signal<CreatedServer | null>(null);
  readonly publicKey = signal<string | null>(null);
  readonly checked = signal<Server | null>(null);

  readonly fetchingHostKey = signal(false);
  readonly hostKeyError = signal<ApiError | null>(null);
  readonly creating = signal(false);
  readonly createError = signal<ApiError | null>(null);
  readonly readingKey = signal(false);
  readonly keyError = signal<ApiError | null>(null);
  readonly checking = signal(false);
  readonly checkError = signal<ApiError | null>(null);

  fetchHostKey(target: HostKeyTarget): Promise<HostKey | null> {
    return this.run(this.api.fingerprint(target), this.fetchingHostKey, this.hostKeyError);
  }

  async create(body: ServerCreate): Promise<CreatedServer | null> {
    const created = await this.run(this.api.create(body), this.creating, this.createError);
    if (created) {
      this.server.set(created);
      this.publicKey.set(created.public_key ?? null);
    }
    return created;
  }

  async rereadPublicKey(): Promise<void> {
    const id = this.server()?.id;
    if (id) {
      const found = await this.run(this.api.publicKey(id), this.readingKey, this.keyError);
      if (found) {
        this.publicKey.set(found.public_key);
      }
    }
  }

  async check(): Promise<boolean> {
    const id = this.server()?.id;
    if (!id) {
      return false;
    }
    const checked = await this.run(this.api.check(id), this.checking, this.checkError);
    this.checked.set(checked);
    return checked !== null;
  }

  private async run<T>(
    request: Observable<T>,
    busy: WritableSignal<boolean>,
    failure: WritableSignal<ApiError | null>,
  ): Promise<T | null> {
    busy.set(true);
    failure.set(null);
    try {
      return await firstValueFrom(request);
    } catch (error) {
      failure.set(error as ApiError);
      return null;
    } finally {
      busy.set(false);
    }
  }
}
