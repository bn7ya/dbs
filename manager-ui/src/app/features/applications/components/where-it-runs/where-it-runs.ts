import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { RunPlace } from './where-it-runs.types';

@Component({
  selector: 'app-where-it-runs',
  imports: [TranslatePipe],
  templateUrl: './where-it-runs.html',
  styleUrl: './where-it-runs.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class WhereItRuns {
  readonly place = input.required<RunPlace>();

  protected readonly icon = computed(() => (this.place().kind === 'host' ? 'fa-solid fa-server' : 'fa-solid fa-cube'));

  protected readonly detail = computed(() => {
    const place = this.place();
    if (place.kind === 'compose') {
      return place.compose_service;
    }
    return place.kind === 'container' ? place.container_name : place.project_dir;
  });

  protected readonly engineKey = computed(() => `applications.engine.${this.place().engine || 'none'}`);
}
