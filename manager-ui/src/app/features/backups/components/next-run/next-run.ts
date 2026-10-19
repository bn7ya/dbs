import { ChangeDetectionStrategy, Component, computed, inject, input } from '@angular/core';

import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { LOCAL_TIME_ZONE, formatIn, shownZone } from '../../data/zoned-time';

@Component({
  selector: 'app-next-run',
  imports: [TranslatePipe],
  templateUrl: './next-run.html',
  styleUrl: './next-run.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NextRun {
  private readonly locale = inject(LocaleStore);
  private readonly localZone = inject(LOCAL_TIME_ZONE);

  readonly at = input.required<string>();
  readonly zone = input.required<string>();

  readonly zoneName = computed(() => shownZone(this.zone()));

  readonly inZone = computed(() => formatIn(this.locale.locale(), this.at(), this.zone()));

  readonly local = computed(() => {
    const local = formatIn(this.locale.locale(), this.at(), this.localZone);
    return local === this.inZone() ? null : local;
  });
}
