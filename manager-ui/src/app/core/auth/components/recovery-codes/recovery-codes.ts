import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { CopyButton } from '@shared/copy-button/copy-button';
import { Notice } from '@shared/notice/notice';

@Component({
  selector: 'app-recovery-codes',
  imports: [CopyButton, Notice, TranslatePipe],
  templateUrl: './recovery-codes.html',
  styleUrl: './recovery-codes.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RecoveryCodes {
  readonly codes = input.required<readonly string[]>();

  protected readonly text = computed(() => this.codes().join('\n'));
}
