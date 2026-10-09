import { DOCUMENT } from '@angular/common';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal, type Signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';
import { MatFormField, MatLabel } from '@angular/material/form-field';
import { MatInput } from '@angular/material/input';
import { MatPaginator, type PageEvent } from '@angular/material/paginator';
import { MatTableModule } from '@angular/material/table';
import { map } from 'rxjs';

import { ErrorTextPipe } from '@core/i18n/error-text.pipe';
import { LocaleStore } from '@core/i18n/locale.store';
import { TranslatePipe } from '@core/i18n/translate.pipe';
import { AppDatePipe } from '@shared/app-date/app-date.pipe';
import { Confirmation } from '@shared/confirm/confirmation';
import { Dialogs } from '@shared/dialogs/dialogs';
import { EmptyState } from '@shared/empty-state/empty-state';
import { FileSizePipe } from '@shared/file-size/file-size.pipe';
import { Notice } from '@shared/notice/notice';
import { PasswordPrompt } from '@shared/password-prompt/password-prompt';
import type { PasswordPromptData } from '@shared/password-prompt/password-prompt.types';
import { Skeleton } from '@shared/skeleton/skeleton';
import { StatusTag } from '@shared/status-tag/status-tag';
import type { ToastSeverity } from '@shared/toaster/toaster.types';
import { Toaster } from '@shared/toaster/toaster';
import { envFileName, type EnvVersion } from '../../data/envfiles.types';
import { ENV_PAGE_SIZES, EnvfilesStore } from '../../state/envfiles.store';
import type { ChangeGroup } from './envfiles.types';

const CONTENT_ROWS_MIN = 4;
const CONTENT_ROWS_MAX = 20;

@Component({
  selector: 'app-envfiles-page',
  imports: [
    RouterLink,
    MatButton,
    MatCard,
    MatCardContent,
    MatFormField,
    MatLabel,
    MatInput,
    MatPaginator,
    MatTableModule,
    Notice,
    Skeleton,
    StatusTag,
    EmptyState,
    AppDatePipe,
    ErrorTextPipe,
    FileSizePipe,
    TranslatePipe,
  ],
  providers: [Dialogs],
  templateUrl: './envfiles.html',
  styleUrl: './envfiles.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EnvfilesPage {
  private readonly store = inject(EnvfilesStore);
  private readonly dialogs = inject(Dialogs);
  private readonly confirmation = inject(Confirmation);
  private readonly toast = inject(Toaster);
  private readonly clipboard = inject(DOCUMENT).defaultView?.navigator.clipboard;
  private readonly locale = inject(LocaleStore);

  readonly serverId = serverIdOf(inject(ActivatedRoute));

  readonly envPath = this.store.envPath;
  readonly noPath = this.store.noPath;
  readonly count = this.store.count;
  readonly page = this.store.page;
  readonly pageSize = this.store.pageSize;
  readonly pageSizes = [...ENV_PAGE_SIZES];
  readonly loading = this.store.loading;
  readonly pending = this.store.pending;
  readonly error = this.store.error;
  readonly empty = this.store.empty;
  readonly pulling = this.store.pulling;
  readonly selected = this.store.selected;
  readonly hasPrevious = this.store.hasPrevious;
  readonly content = this.store.content;
  readonly comparison = this.store.comparison;
  readonly compareError = this.store.compareError;
  readonly comparing = this.store.comparing;

  readonly rows = computed(() => [...this.store.versions()]);

  readonly offerPull = computed(() => !this.noPath() && !this.empty());

  readonly overviewLink = computed(() => ['/servers', this.serverId() ?? '']);

  readonly paginated = computed(() => this.count() > ENV_PAGE_SIZES[0]);

  readonly skeletonLines = [0, 1, 2, 3, 4, 5];

  readonly changes = computed<readonly ChangeGroup[]>(() => {
    const comparison = this.comparison();
    if (comparison === null) {
      return [];
    }
    const groups: readonly ChangeGroup[] = [
      { labelKey: 'envfiles.compare.added', keys: comparison.added },
      { labelKey: 'envfiles.compare.removed', keys: comparison.removed },
      { labelKey: 'envfiles.compare.changed', keys: comparison.changed },
    ];
    return groups.filter((group) => group.keys.length > 0);
  });

  readonly contentRows = computed(() => {
    const lines = (this.content() ?? '').split('\n').length;
    return Math.min(CONTENT_ROWS_MAX, Math.max(CONTENT_ROWS_MIN, lines));
  });

  readonly fileName = computed(() => envFileName(this.selected()?.path ?? ''));

  readonly downloadHref = signal<string | null>(null);

  constructor() {
    effect(() => {
      const server = this.serverId();
      if (server !== null) {
        this.store.open(server);
      }
    });
    inject(DestroyRef).onDestroy(() => this.store.close());

    effect((onCleanup) => {
      const content = this.content();
      if (content === null) {
        this.downloadHref.set(null);
        return;
      }
      const href = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }));
      this.downloadHref.set(href);
      onCleanup(() => URL.revokeObjectURL(href));
    });
  }

  isSelected(version: EnvVersion): boolean {
    return this.selected()?.id === version.id;
  }

  select(version: EnvVersion): void {
    this.store.select(version);
  }

  takenBy(version: EnvVersion): string | null {
    return version.taken_by === null ? null : this.locale.translate('envfiles.list.by', { name: isolated(version.taken_by) });
  }

  pull(): void {
    void this.store.pull();
  }

  async toggleValues(version: EnvVersion): Promise<void> {
    if (this.content() !== null) {
      this.store.hide();
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'envfiles.reveal.prompt.title',
      bodyKey: 'envfiles.reveal.prompt.body',
      submitKey: 'envfiles.reveal.show',
      submit: (password) => this.store.reveal(version, password),
      error: this.store.revealError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  async copy(content: string): Promise<void> {
    try {
      if (!this.clipboard) {
        throw new Error('No clipboard');
      }
      await this.clipboard.writeText(content);
      this.notify('success', 'envfiles.reveal.copied');
    } catch {
      this.notify('warning', 'envfiles.reveal.copyUnavailable');
    }
  }

  compare(): void {
    void this.store.compare();
  }

  async push(version: EnvVersion): Promise<void> {
    const accepted = await this.confirmation.ask({
      title: this.locale.translate('envfiles.push.confirmTitle'),
      message: leftToRight(this.envPath() || version.path),
      detail: this.locale.translate('envfiles.push.confirmBody'),
      acceptLabel: this.locale.translate('envfiles.push.confirmAccept'),
      rejectLabel: this.locale.translate('actions.cancel'),
      acceptSeverity: 'danger',
    });
    if (!accepted) {
      return;
    }
    const data: PasswordPromptData = {
      titleKey: 'envfiles.push.prompt.title',
      bodyKey: 'envfiles.push.prompt.body',
      submitKey: 'envfiles.push.prompt.submit',
      submit: (password) => this.store.push(version, password),
      error: this.store.pushError,
    };
    await this.dialogs
      .open<boolean, PasswordPromptData>(PasswordPrompt, { titleKey: data.titleKey, data, size: 'sm' })
      .whenClosed();
  }

  onPage(event: PageEvent): void {
    this.store.goToPage(event.pageIndex, event.pageSize);
  }

  retry(): void {
    this.store.reload();
  }

  private notify(severity: ToastSeverity, key: string): void {
    this.toast.add({ severity, summary: this.locale.translate(key) });
  }
}

function isolated(text: string): string {
  return `⁨${text}⁩`;
}

// The confirmation takes a plain string, so the path carries its own left-to-right isolate.
function leftToRight(text: string): string {
  return `⁦${text}⁩`;
}

// Param inheritance stops at the server page (a route with its own component), so read the route that declares it.
function serverIdOf(route: ActivatedRoute): Signal<string | null> {
  const owner = route.pathFromRoot.find((step) => step.snapshot.paramMap.has('serverId'));
  if (!owner) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get('serverId'))), { requireSync: true });
}
