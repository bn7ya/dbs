import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButton } from '@angular/material/button';
import { MatListItem, MatListItemIcon, MatListItemTitle, MatNavList } from '@angular/material/list';
import { MatMenu, MatMenuItem, MatMenuTrigger } from '@angular/material/menu';
import { MatToolbar } from '@angular/material/toolbar';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthStore } from '@core/auth/state/auth.store';
import { LocaleSwitcher } from '@core/i18n/locale-switcher/locale-switcher';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { SHELL_FRAME } from '../shell-frame';
import { SECTIONS } from './app-layout.types';

@Component({
  selector: 'app-layout',
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    MatButton,
    MatToolbar,
    MatMenu,
    MatMenuItem,
    MatMenuTrigger,
    MatNavList,
    MatListItem,
    MatListItemIcon,
    MatListItemTitle,
    LocaleSwitcher,
    TranslatePipe,
  ],
  providers: [{ provide: SHELL_FRAME, useValue: true }],
  templateUrl: './app-layout.html',
  styleUrl: './app-layout.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppLayout {
  private readonly auth = inject(AuthStore);

  readonly displayName = this.auth.displayName;
  readonly signingOut = this.auth.busy;

  readonly sections = SECTIONS;

  signOut(): void {
    void this.auth.signOut();
  }
}
