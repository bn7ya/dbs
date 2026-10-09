import { ChangeDetectionStrategy, Component, booleanAttribute, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';

const KEY_FILES: Readonly<Record<string, string>> = {
  'ssh-ed25519': 'ssh_host_ed25519_key.pub',
  'ecdsa-sha2-nistp256': 'ssh_host_ecdsa_key.pub',
  'ecdsa-sha2-nistp384': 'ssh_host_ecdsa_key.pub',
  'ecdsa-sha2-nistp521': 'ssh_host_ecdsa_key.pub',
  'ssh-rsa': 'ssh_host_rsa_key.pub',
};

@Component({
  selector: 'app-host-key-facts',
  imports: [TranslatePipe],
  templateUrl: './host-key-facts.html',
  styleUrl: './host-key-facts.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class HostKeyFacts {
  readonly keyType = input.required<string>();
  readonly fingerprint = input.required<string>();
  readonly compare = input(false, { transform: booleanAttribute });

  protected readonly command = computed(
    () => `ssh-keygen -lf /etc/ssh/${KEY_FILES[this.keyType()] ?? KEY_FILES['ssh-ed25519']}`,
  );
}
