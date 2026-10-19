import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, input } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet, type IsActiveMatchOptions } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatTabLink, MatTabNav, MatTabNavPanel } from '@angular/material/tabs';

import { AuthStore } from '@core/auth/state/auth.store';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { ConnectionDot } from '@shared/connection-dot/connection-dot';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { ServersStore } from '../../state/servers.store';
import type { ServerTab } from './server.types';

// `.` is the overview: an empty link would resolve to the manager's root, not this route.
const TABS: readonly ServerTab[] = [
  { path: '.', labelKey: 'servers.page.overview' },
  { path: 'applications', labelKey: 'servers.page.applications' },
  { path: 'terminal', labelKey: 'servers.page.terminal', capability: 'shell.open' },
  { path: 'activity', labelKey: 'servers.page.activity' },
];

const TAB_MATCH: IsActiveMatchOptions = {
  paths: 'exact',
  queryParams: 'ignored',
  matrixParams: 'ignored',
  fragment: 'ignored',
};

@Component({
  selector: 'app-server-page',
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    MatButton,
    MatTabNav,
    MatTabLink,
    MatTabNavPanel,
    Notice,
    Skeleton,
    EmptyState,
    CheckStatusTag,
    ConnectionDot,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './server.html',
  styleUrl: './server.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerPage {
  private readonly store = inject(ServersStore);
  private readonly auth = inject(AuthStore);

  readonly serverId = input.required<string>();

  readonly tabs = computed(() => TABS.filter((tab) => !tab.capability || this.auth.can(tab.capability)));
  readonly tabMatch = TAB_MATCH;
  readonly skeletonLines = [1, 2, 3];
  readonly server = this.store.server;
  readonly error = this.store.serverError;
  readonly missing = this.store.serverMissing;

  constructor() {
    effect(() => this.store.select(this.serverId()));
    inject(DestroyRef).onDestroy(() => this.store.select(undefined));
  }

  retry(): void {
    this.store.reloadServer();
  }
}
