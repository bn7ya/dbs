import { Injectable, effect, inject } from '@angular/core';
import { MatDatepickerIntl } from '@angular/material/datepicker';

import { LocaleStore } from '@core/i18n/locale.store';

@Injectable()
export class MomentIntl extends MatDatepickerIntl {
  private readonly locale = inject(LocaleStore);

  constructor() {
    super();
    effect(() => {
      const t = (key: string): string => this.locale.translate(`backups.moment.calendar.${key}`);
      this.calendarLabel = t('label');
      this.openCalendarLabel = t('open');
      this.closeCalendarLabel = t('close');
      this.prevMonthLabel = t('previousMonth');
      this.nextMonthLabel = t('nextMonth');
      this.prevYearLabel = t('previousYear');
      this.nextYearLabel = t('nextYear');
      this.prevMultiYearLabel = t('previousYears');
      this.nextMultiYearLabel = t('nextYears');
      this.switchToMonthViewLabel = t('chooseDate');
      this.switchToMultiYearViewLabel = t('chooseMonthAndYear');
      this.changes.next();
    });
  }
}
