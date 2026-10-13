import { ChangeDetectionStrategy, Component, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { TimeAgoPipe } from '@shared/time-ago/time-ago.pipe';
import type { ConnectionState } from './connection-dot.types';

@Component({
  selector: 'app-connection-dot',
  imports: [TimeAgoPipe, TranslatePipe],
  templateUrl: './connection-dot.html',
  styleUrl: './connection-dot.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class]': '"connection-dot connection-dot--" + state()',
  },
})
export class ConnectionDot {
  readonly state = input.required<ConnectionState>();
  readonly lastSeenAt = input<string | null>(null);
}
