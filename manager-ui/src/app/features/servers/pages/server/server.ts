import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, input } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet, type IsActiveMatchOptions } from '@angular/router';
import { ButtonDirective } from 'primeng/button';
import { Message } from 'primeng/message';
import { Skeleton } from 'primeng/skeleton';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { EmptyState } from '@shared/empty-state/empty-state';
import { CheckStatusTag } from '../../components/check-status-tag/check-status-tag';
import { ServersStore } from '../../state/servers.store';
import type { ServerTab } from './server.types';

// `.` is the overview: an empty link would resolve to the application's root, not this route.
const TABS: readonly ServerTab[] = [
  { path: '.', labelKey: 'servers.page.overview' },
  { path: 'backups', labelKey: 'servers.page.backups' },
  { path: 'files', labelKey: 'servers.page.files' },
  { path: 'environment', labelKey: 'servers.page.environment' },
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
    ButtonDirective,
    Message,
    Skeleton,
    EmptyState,
    CheckStatusTag,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './server.html',
  styleUrl: './server.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ServerPage {
  private readonly store = inject(ServersStore);

  readonly serverId = input.required<string>();

  readonly tabs = TABS;
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
