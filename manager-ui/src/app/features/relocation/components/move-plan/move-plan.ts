import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { Notice } from '@shared/notice/notice';
import type { MoveDetail, MoveFact } from '../../data/relocation.types';

@Component({
  selector: 'app-move-plan',
  imports: [FileSizePipe, Notice, TranslatePipe],
  templateUrl: './move-plan.html',
  styleUrl: './move-plan.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MovePlan {
  readonly detail = input.required<MoveDetail>();

  protected readonly inventory = computed(() => this.detail().inventory);
  protected readonly system = computed(() => this.inventory()?.target.system ?? null);
  protected readonly packages = computed(() => this.inventory()?.packages.packages ?? []);
  protected readonly notes = computed(() => this.inventory()?.notes ?? []);

  values(fact: MoveFact): Readonly<Record<string, string>> {
    return {
      application: fact.application ?? '',
      path: fact.path ?? '',
      volume: fact.volume ?? '',
      image: fact.image ?? '',
      name: fact.name ?? fact.site ?? '',
      source: fact.source ?? '',
      target: fact.target ?? '',
    };
  }

  short(head: string): string {
    return head.slice(0, 12);
  }
}
