import type { Params } from '@angular/router';

export interface BreadcrumbItem {
  readonly label: string;
  readonly link: readonly unknown[];
  readonly queryParams?: Params;
  readonly icon?: string;
}
