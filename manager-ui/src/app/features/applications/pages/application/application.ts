import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject } from '@angular/core';
import { ActivatedRoute, RouterLink, RouterLinkActive, RouterOutlet, type IsActiveMatchOptions } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatTabLink, MatTabNav, MatTabNavPanel } from '@angular/material/tabs';

import { AuthStore } from '@core/auth/state/auth.store';
import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { routeParam } from '@core/routing/route-param';
import { ConnectionDot } from '@shared/connection-dot/connection-dot';
import { EmptyState } from '@shared/empty-state/empty-state';
import { Notice } from '@shared/notice/notice';
import { Skeleton } from '@shared/skeleton/skeleton';
import { CheckTag } from '../../components/check-tag/check-tag';
import { WhereItRuns } from '../../components/where-it-runs/where-it-runs';
import { ApplicationsStore } from '../../state/applications.store';
import type { ApplicationTab } from './application.types';

// `.` is the overview: an empty link would resolve to the manager's root, not this route.
const TABS: readonly ApplicationTab[] = [
  { path: '.', labelKey: 'applications.page.overview' },
  { path: 'backups', labelKey: 'applications.page.backups' },
  { path: 'schedule', labelKey: 'applications.page.schedule' },
  { path: 'files', labelKey: 'applications.page.files' },
  { path: 'environment', labelKey: 'applications.page.environment' },
  { path: 'deploy', labelKey: 'applications.page.deploy', capability: 'redeploy.rehearse' },
  { path: 'terminal', labelKey: 'applications.page.terminal', capability: 'shell.open' },
  { path: 'activity', labelKey: 'applications.page.activity' },
];

const TAB_MATCH: IsActiveMatchOptions = {
  paths: 'exact',
  queryParams: 'ignored',
  matrixParams: 'ignored',
  fragment: 'ignored',
};

@Component({
  selector: 'app-application-page',
  imports: [
    RouterLink,
    RouterLinkActive,
    RouterOutlet,
    MatButton,
    MatTabNav,
    MatTabLink,
    MatTabNavPanel,
    ConnectionDot,
    EmptyState,
    Notice,
    Skeleton,
    CheckTag,
    WhereItRuns,
    ErrorTextPipe,
    TranslatePipe,
  ],
  templateUrl: './application.html',
  styleUrl: './application.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ApplicationPage {
  private readonly store = inject(ApplicationsStore);
  private readonly auth = inject(AuthStore);

  readonly applicationId = routeParam(inject(ActivatedRoute), 'applicationId');

  readonly tabs = computed(() => TABS.filter((tab) => !tab.capability || this.auth.can(tab.capability)));
  readonly tabMatch = TAB_MATCH;
  readonly skeletonLines = [1, 2, 3];
  readonly application = this.store.application;
  readonly error = this.store.applicationError;
  readonly missing = this.store.applicationMissing;

  constructor() {
    effect(() => this.store.select(this.applicationId() ?? undefined));
    inject(DestroyRef).onDestroy(() => this.store.select(undefined));
  }

  retry(): void {
    this.store.reloadApplication();
  }
}
