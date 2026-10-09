import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import type { StatusTagSeverity } from './status-tag.types';

@Component({
  selector: 'app-status-tag',
  templateUrl: './status-tag.html',
  styleUrl: './status-tag.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class]': '"status-tag status-tag--" + severity()',
  },
})
export class StatusTag {
  readonly severity = input<StatusTagSeverity>('neutral');
  readonly icon = input('');
  readonly label = input.required<string>();
}
