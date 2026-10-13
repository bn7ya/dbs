import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class CsrfToken {
  private readonly held = signal<string | null>(null);

  readonly value = this.held.asReadonly();

  hold(token: string): void {
    this.held.set(token);
  }

  forget(): void {
    this.held.set(null);
  }
}
