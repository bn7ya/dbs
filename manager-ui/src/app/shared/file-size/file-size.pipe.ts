import { Pipe, inject, type PipeTransform } from '@angular/core';

import { LocaleStore } from '@core/i18n/locale.store';

const SIZE_UNITS = ['kilobyte', 'megabyte', 'gigabyte', 'terabyte'] as const;
const SIZE_STEP = 1000;

@Pipe({ name: 'fileSize', pure: false })
export class FileSizePipe implements PipeTransform {
  private readonly locale = inject(LocaleStore);

  transform(bytes: number): string {
    if (bytes < SIZE_STEP) {
      return this.format(bytes, { unit: 'byte', unitDisplay: 'long' });
    }
    let value: number = bytes / SIZE_STEP;
    let step = 0;
    while (value >= SIZE_STEP && step < SIZE_UNITS.length - 1) {
      value /= SIZE_STEP;
      step += 1;
    }
    return this.format(value, { unit: SIZE_UNITS[step], unitDisplay: 'short', maximumFractionDigits: 1 });
  }

  private format(value: number, options: Intl.NumberFormatOptions): string {
    return new Intl.NumberFormat(this.locale.locale(), {
      style: 'unit',
      numberingSystem: 'latn',
      ...options,
    }).format(value);
  }
}
