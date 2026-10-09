import type { Translation } from 'primeng/api';

export function primeTranslation(translate: (key: string) => string): Translation {
  return {
    emptyMessage: translate('components.empty'),
    emptyFilterMessage: translate('components.empty'),
    emptySearchMessage: translate('components.empty'),
    aria: {
      close: translate('components.close'),
      firstPageLabel: translate('components.firstPage'),
      lastPageLabel: translate('components.lastPage'),
      nextPageLabel: translate('components.nextPage'),
      prevPageLabel: translate('components.previousPage'),
      previousPageLabel: translate('components.previousPage'),
      pageLabel: translate('components.page'),
      rowsPerPageLabel: translate('components.rowsPerPage'),
    },
  };
}
