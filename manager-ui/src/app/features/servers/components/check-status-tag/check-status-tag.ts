import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { CheckStatus } from '../../data/servers.types';
import type { CheckStatusLook } from './check-status-tag.types';

const LOOKS: Readonly<Record<CheckStatus, CheckStatusLook>> = {
  unknown: { severity: 'neutral', icon: 'fa-solid fa-circle-question' },
  ok: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  problem: { severity: 'warning', icon: 'fa-solid fa-triangle-exclamation' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
};

@Component({
  selector: 'app-check-status-tag',
  imports: [StatusTag, TranslatePipe],
  templateUrl: './check-status-tag.html',
  styleUrl: './check-status-tag.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CheckStatusTag {
  readonly status = input.required<CheckStatus>();

  protected readonly look = computed(() => LOOKS[this.status()]);
}
