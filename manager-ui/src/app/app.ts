import { ChangeDetectionStrategy, Component, effect, inject } from '@angular/core';
import { RouterOutlet } from '@angular/router';
import { PrimeNG } from 'primeng/config';

import { LocaleStore } from '@core/i18n/locale.store';
import { primeTranslation } from '@core/i18n/primeng-translation';
import { TranslatePipe } from '@core/i18n/translate.pipe';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, TranslatePipe],
  templateUrl: './app.html',
  styleUrl: './app.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class App {
  private readonly locale = inject(LocaleStore);

  private readonly primeng = inject(PrimeNG);

  readonly direction = this.locale.direction;

  constructor() {
    effect(() => this.primeng.setTranslation(primeTranslation((key) => this.locale.translate(key))));
  }
}
