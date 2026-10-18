import { ChangeDetectionStrategy, Component, effect, inject, input, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DateAdapter, provideNativeDateAdapter } from '@angular/material/core';
import {
  MatDatepicker,
  MatDatepickerInput,
  MatDatepickerIntl,
  MatDatepickerToggle,
  MatDatepickerToggleIcon,
} from '@angular/material/datepicker';
import { MatError, MatFormField, MatHint, MatLabel, MatSuffix } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatTimepicker, MatTimepickerInput, MatTimepickerToggle } from '@angular/material/timepicker';

import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FieldError } from '@shared/field/field-error';
import { MomentIntl } from './moment-intl';

const DAYS_AHEAD = 366;

@Component({
  selector: 'app-moment-fields',
  imports: [
    FormsModule,
    MatFormField,
    MatLabel,
    MatHint,
    MatError,
    MatSuffix,
    MatInput,
    MatDatepicker,
    MatDatepickerInput,
    MatDatepickerToggle,
    MatDatepickerToggleIcon,
    MatTimepicker,
    MatTimepickerInput,
    MatTimepickerToggle,
    FieldError,
    TranslatePipe,
  ],
  providers: [provideNativeDateAdapter(), { provide: MatDatepickerIntl, useClass: MomentIntl }],
  templateUrl: './moment-fields.html',
  styleUrl: './moment-fields.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MomentFields {
  private readonly locale = inject(LocaleStore);
  private readonly adapter = inject<DateAdapter<Date>>(DateAdapter);

  readonly day = model<Date | null>(null);
  readonly time = model<Date | null>(null);

  readonly name = input.required<string>();
  readonly dayLabel = input.required<string>();
  readonly timeLabel = input.required<string>();
  readonly hint = input('');
  readonly dayError = input('');
  readonly timeError = input('');

  readonly earliest = startOfToday();
  readonly latest = daysAfter(this.earliest, DAYS_AHEAD);

  constructor() {
    // Dates are written the way the rest of the page writes them: Gregorian, with Latin digits.
    effect(() => this.adapter.setLocale(`${this.locale.locale()}-u-ca-gregory-nu-latn`));
  }
}

function startOfToday(): Date {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function daysAfter(day: Date, days: number): Date {
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() + days);
}
