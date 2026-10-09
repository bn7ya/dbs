import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ButtonDirective } from 'primeng/button';
import { Checkbox } from 'primeng/checkbox';
import { Message } from 'primeng/message';
import { Skeleton } from 'primeng/skeleton';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { injectDialogRef } from '@shared/dialogs/dialogs';
import { Field } from '@shared/field/field';
import { PasswordInput } from '@shared/password-input/password-input';
import { uniqueId } from '@shared/unique-id';
import type { HostKey } from '../../data/servers.types';
import { ServersStore } from '../../state/servers.store';
import { HostKeyFacts } from '../host-key-facts/host-key-facts';

@Component({
  selector: 'app-host-key-review',
  imports: [
    FormsModule,
    ButtonDirective,
    Checkbox,
    Message,
    Skeleton,
    Field,
    PasswordInput,
    HostKeyFacts,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './host-key-review.html',
  styleUrl: './host-key-review.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HostKeyReview {
  private readonly store = inject(ServersStore);
  private readonly ref = injectDialogRef<boolean>();

  protected readonly confirmId = uniqueId('host-key-confirmed');
  protected readonly skeletonLines = [1, 2, 3];

  readonly server = this.store.server;
  readonly fetching = this.store.fetchingHostKey;
  readonly fetchError = this.store.hostKeyError;
  readonly pinning = this.store.repinning;

  readonly presented = signal<HostKey | null>(null);
  readonly confirmed = signal(false);
  readonly password = signal('');
  private readonly submitted = signal(false);

  readonly unchanged = computed(() => {
    const presented = this.presented();
    return presented !== null && presented.fingerprint === this.server()?.host_key_fingerprint;
  });
  readonly canPin = computed(() => this.presented() !== null && !this.unchanged());

  readonly unconfirmed = computed(() => this.submitted() && !this.confirmed());
  readonly passwordMissing = computed(() => this.submitted() && this.password() === '');

  readonly rejected = computed(() => this.store.repinError()?.code === 'invalid_password');
  readonly pinFailure = computed(() => {
    const failure = this.store.repinError();
    return failure && failure.code !== 'invalid_password' ? failure : null;
  });

  constructor() {
    this.store.resetHostKeyReview();
    void this.fetch();
  }

  async fetch(): Promise<void> {
    const server = this.server();
    if (!server) {
      return;
    }
    this.confirmed.set(false);
    this.presented.set(await this.store.fetchHostKey({ host: server.host, port: server.port }));
  }

  async pin(): Promise<void> {
    this.submitted.set(true);
    const presented = this.presented();
    if (!presented || !this.canPin() || !this.confirmed() || this.password() === '') {
      return;
    }
    if (await this.store.repinHostKey(presented.line, this.password())) {
      this.ref.close(true);
    }
  }

  close(): void {
    this.ref.close();
  }
}
