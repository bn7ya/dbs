import type { Signal } from '@angular/core';
import { signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import type { ActivatedRoute } from '@angular/router';
import { map } from 'rxjs';

export function routeParam(route: ActivatedRoute, name: string): Signal<string | null> {
  const owner = [...route.pathFromRoot].reverse().find((step) => step.snapshot.paramMap.has(name));
  if (owner === undefined) {
    return signal(null).asReadonly();
  }
  return toSignal(owner.paramMap.pipe(map((params) => params.get(name))), { requireSync: true });
}
