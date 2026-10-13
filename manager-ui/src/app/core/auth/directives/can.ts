import { Directive, TemplateRef, ViewContainerRef, effect, inject, input } from '@angular/core';

import type { Capability } from '../data/auth.types';
import { AuthStore } from '../state/auth.store';

@Directive({ selector: '[appCan]' })
export class Can {
  private readonly auth = inject(AuthStore);
  private readonly template = inject<TemplateRef<unknown>>(TemplateRef);
  private readonly container = inject(ViewContainerRef);

  readonly appCan = input.required<Capability>();

  private shown = false;

  constructor() {
    // Hidden only when the signed-in role lacks it; the backend refuses whatever is left.
    effect(() => {
      const allowed = !this.auth.forbids(this.appCan());
      if (allowed && !this.shown) {
        this.container.createEmbeddedView(this.template);
      } else if (!allowed && this.shown) {
        this.container.clear();
      }
      this.shown = allowed;
    });
  }
}
