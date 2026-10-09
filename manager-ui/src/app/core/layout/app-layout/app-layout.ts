import { ChangeDetectionStrategy, Component, computed, inject } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';
import type { MenuItem } from 'primeng/api';
import { ButtonDirective } from 'primeng/button';
import { Menu } from 'primeng/menu';

import { AuthStore } from '@core/auth/state/auth.store';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SHELL_FRAME } from '../shell-frame';
import { SECTIONS } from './app-layout.types';

@Component({
  selector: 'app-layout',
  imports: [RouterLink, RouterOutlet, ButtonDirective, Menu, LocaleSwitcher, TranslatePipe],
  providers: [{ provide: SHELL_FRAME, useValue: true }],
  templateUrl: './app-layout.html',
  styleUrl: './app-layout.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppLayout {
  private readonly auth = inject(AuthStore);
  private readonly locale = inject(LocaleStore);

  readonly displayName = this.auth.displayName;
  readonly signingOut = this.auth.busy;

  readonly items = computed<MenuItem[]>(() =>
    SECTIONS.map((section) => ({
      label: this.locale.translate(section.labelKey),
      icon: section.icon,
      routerLink: ['/', section.path],
    })),
  );

  signOut(): void {
    void this.auth.signOut();
  }
}
