import { EnvironmentInjector, Injectable, Injector, inject, runInInjectionContext, type Type } from '@angular/core';
import { DialogService, DynamicDialogConfig, DynamicDialogRef } from 'primeng/dynamicdialog';
import { EMPTY, firstValueFrom, map, take, type Observable } from 'rxjs';

import { LocaleStore } from '@core/i18n/locale.store';
import type { DialogHandle, DialogOptions } from './dialogs.types';

@Injectable()
export class Dialogs {
  private readonly locale = inject(LocaleStore);
  // DynamicDialog builds its content from the injector the service was made in; made here, a feature store provided by the route stays visible.
  private readonly service = runInInjectionContext(
    Injector.create({ providers: [], parent: inject(EnvironmentInjector) }),
    () => new DialogService(),
  );

  open<R, D = undefined>(component: Type<unknown>, options: DialogOptions<D>): DialogHandle<R> {
    const ref: DynamicDialogRef<unknown> | null = this.service.open(component, {
      header: this.locale.translate(options.titleKey),
      data: options.data,
      modal: true,
      closable: true,
      closeOnEscape: true,
      rtl: this.locale.isRtl(),
      styleClass: `app-dialog app-dialog--${options.size ?? 'md'}`,
    });
    const closed: Observable<R | undefined> =
      ref === null ? EMPTY : ref.onClose.pipe(take(1), map((result: unknown) => result as R | undefined));
    return {
      closed,
      whenClosed: () => firstValueFrom(closed, { defaultValue: undefined }),
    };
  }
}

export function injectDialogData<D>(): D {
  return inject(DynamicDialogConfig<D>).data as D;
}

export function injectDialogRef<R>(): DynamicDialogRef<unknown> & { close(result?: R): void } {
  return inject(DynamicDialogRef);
}
