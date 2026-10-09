import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';
import { RouterLink } from '@angular/router';

import type { BreadcrumbItem } from './breadcrumb.types';

@Component({
  selector: 'app-breadcrumb',
  imports: [RouterLink],
  templateUrl: './breadcrumb.html',
  styleUrl: './breadcrumb.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class Breadcrumb {
  readonly items = input.required<readonly BreadcrumbItem[]>();
  readonly label = input.required<string>();
  readonly code = input(false, { transform: booleanAttribute });
}
