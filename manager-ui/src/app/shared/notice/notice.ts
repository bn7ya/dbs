import { ChangeDetectionStrategy, Component, booleanAttribute, computed, input, output } from '@angular/core';
import { MatIconButton } from '@angular/material/button';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { NOTICE_ICON, type NoticeSeverity } from './notice.types';

@Component({
  selector: 'app-notice',
  imports: [MatIconButton, TranslatePipe],
  templateUrl: './notice.html',
  styleUrl: './notice.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '[class]': '"notice notice--" + severity()',
    '[attr.role]': 'role()',
  },
})
export class Notice {
  readonly severity = input<NoticeSeverity>('info');
  readonly closable = input(false, { transform: booleanAttribute });
  readonly closed = output();

  protected readonly icon = computed(() => NOTICE_ICON[this.severity()]);
  protected readonly role = computed(() =>
    this.severity() === 'danger' || this.severity() === 'warning' ? 'alert' : 'status',
  );
}
