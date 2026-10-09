import { Injectable, effect, inject } from '@angular/core';
import { MatPaginatorIntl } from '@angular/material/paginator';

import { LocaleStore } from './locale.store';

@Injectable()
export class AppPaginatorIntl extends MatPaginatorIntl {
  private readonly locale = inject(LocaleStore);

  constructor() {
    super();
    effect(() => {
      const t = (key: string): string => this.locale.translate(key);
      this.itemsPerPageLabel = t('components.rowsPerPage');
      this.firstPageLabel = t('components.firstPage');
      this.lastPageLabel = t('components.lastPage');
      this.nextPageLabel = t('components.nextPage');
      this.previousPageLabel = t('components.previousPage');
      this.changes.next();
    });
  }

  override getRangeLabel = (page: number, pageSize: number, length: number): string => {
    if (length === 0 || pageSize === 0) {
      return this.locale.translate('components.range', { start: 0, end: 0, total: length });
    }
    const start = page * pageSize;
    const end = Math.min(start + pageSize, length);
    return this.locale.translate('components.range', { start: start + 1, end, total: length });
  };
}
