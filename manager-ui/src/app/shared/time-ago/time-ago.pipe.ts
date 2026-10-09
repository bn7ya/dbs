import { Pipe, inject, type PipeTransform } from '@angular/core';

import { LocaleStore } from '@core/i18n/locale.store';
import { TIME_STEPS } from './time-ago.types';

@Pipe({ name: 'timeAgo', pure: false })
export class TimeAgoPipe implements PipeTransform {
  private readonly locale = inject(LocaleStore);

  transform(value: string | null | undefined): string {
    if (!value) {
      return '';
    }
    const seconds = Math.round((new Date(value).getTime() - Date.now()) / 1000);
    const format = new Intl.RelativeTimeFormat(`${this.locale.locale()}-u-nu-latn`, { numeric: 'auto' });
    const step = TIME_STEPS.find((each) => Math.abs(seconds) < each.below) ?? TIME_STEPS[TIME_STEPS.length - 1];
    return format.format(Math.round(seconds / step.seconds), step.unit);
  }
}
