import { ChangeDetectionStrategy, Component, booleanAttribute, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import type { BrandMarkSize } from './brand-mark.types';

@Component({
  selector: 'app-brand-mark',
  imports: [TranslatePipe],
  templateUrl: './brand-mark.html',
  styleUrl: './brand-mark.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { '[class.brand-mark--large]': "size() === 'large'" },
})
export class BrandMark {
  readonly size = input<BrandMarkSize>('small');
  readonly decorative = input(false, { transform: booleanAttribute });
}
