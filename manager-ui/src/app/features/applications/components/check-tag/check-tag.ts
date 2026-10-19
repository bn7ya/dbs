import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { CheckStatus } from '../../data/applications.types';
import type { CheckLook } from './check-tag.types';

const LOOKS: Readonly<Record<CheckStatus, CheckLook>> = {
  unknown: { severity: 'neutral', icon: 'fa-solid fa-circle-question' },
  ok: { severity: 'success', icon: 'fa-solid fa-circle-check' },
  problem: { severity: 'warning', icon: 'fa-solid fa-triangle-exclamation' },
  failed: { severity: 'danger', icon: 'fa-solid fa-circle-xmark' },
};

@Component({
  selector: 'app-check-tag',
  imports: [StatusTag, TranslatePipe],
  templateUrl: './check-tag.html',
  styleUrl: './check-tag.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CheckTag {
  readonly status = input.required<CheckStatus>();

  protected readonly look = computed(() => LOOKS[this.status()]);
}
