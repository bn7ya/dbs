import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  afterNextRender,
  effect,
  inject,
  input,
  output,
  viewChild,
} from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import type { ITheme } from '@xterm/xterm';
import { Observable, debounceTime } from 'rxjs';

import { TERMINAL_SCREENS } from './terminal-screens';
import type { TerminalScreen, TerminalScreenParts, TerminalSize, ThemeColour } from './terminal-view.types';

export const TERMINAL_FIT_DEBOUNCE_MS = 100;

const SCROLLBACK_LINES = 5000;

const FONT_TOKEN = '--app-font-mono';

// The ground is light, so white and bright white take dark tokens to stay readable on it.
const THEME_TOKENS: Readonly<Partial<Record<ThemeColour, string>>> = {
  background: '--app-color-surface',
  foreground: '--app-color-on-surface',
  cursor: '--app-color-primary',
  cursorAccent: '--app-color-on-primary',
  selectionBackground: '--app-color-primary-container',
  selectionForeground: '--app-color-on-primary-container',
  black: '--app-color-on-surface',
  red: '--app-color-danger',
  green: '--app-color-success',
  yellow: '--app-color-warning',
  blue: '--app-color-primary',
  magenta: '--app-color-on-primary-container',
  cyan: '--app-color-info',
  white: '--app-color-on-surface-variant',
  brightBlack: '--app-color-on-surface-variant',
  brightRed: '--app-color-danger',
  brightGreen: '--app-color-success',
  brightYellow: '--app-color-warning',
  brightBlue: '--app-color-primary',
  brightMagenta: '--app-color-on-primary-container',
  brightCyan: '--app-color-info',
  brightWhite: '--app-color-on-surface',
};

@Component({
  selector: 'app-terminal-view',
  templateUrl: './terminal-view.html',
  styleUrl: './terminal-view.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TerminalView {
  private readonly screens = inject(TERMINAL_SCREENS);
  private readonly destroyRef = inject(DestroyRef);

  readonly label = input.required<string>();
  readonly tooMuchOutput = input.required<string>();
  readonly interactive = input(true);

  readonly typed = output<string>();
  readonly resized = output<TerminalSize>();

  private readonly frame = viewChild.required<ElementRef<HTMLElement>>('frame');

  private readonly parts: TerminalScreenParts = this.screens.create({
    screenReaderMode: true,
    scrollback: SCROLLBACK_LINES,
  });

  constructor() {
    effect(() => this.screens.localize({ promptLabel: this.label(), tooMuchOutput: this.tooMuchOutput() }));
    effect(() => {
      const label = this.label();
      this.parts.screen.textarea?.setAttribute('aria-label', label);
    });
    effect(() => {
      this.parts.screen.options.disableStdin = !this.interactive();
    });
    afterNextRender(() => this.start());
    this.destroyRef.onDestroy(() => this.parts.screen.dispose());
  }

  write(data: Uint8Array): void {
    this.parts.screen.write(data);
  }

  clear(): void {
    this.parts.screen.reset();
  }

  focus(): void {
    this.parts.screen.focus();
  }

  private start(): void {
    const element = this.frame().nativeElement;
    const { screen, fitter } = this.parts;
    dress(screen, getComputedStyle(element));
    screen.open(element);
    fitter.fit();
    this.resized.emit(sizeOf(screen));
    screen.onData((data) => this.typed.emit(data));
    screen.onResize((size) => this.resized.emit(sizeOf(size)));
    resizesOf(element)
      .pipe(debounceTime(TERMINAL_FIT_DEBOUNCE_MS), takeUntilDestroyed(this.destroyRef))
      .subscribe(() => fitter.fit());
  }
}

function dress(screen: TerminalScreen, style: CSSStyleDeclaration): void {
  screen.options.theme = themeOf(style);
  const fontFamily = style.getPropertyValue(FONT_TOKEN).trim();
  if (fontFamily !== '') {
    screen.options.fontFamily = fontFamily;
  }
  const fontSize = Number.parseFloat(style.fontSize);
  if (Number.isFinite(fontSize) && fontSize > 0) {
    screen.options.fontSize = fontSize;
  }
}

function themeOf(style: CSSStyleDeclaration): ITheme {
  const theme: Partial<Record<ThemeColour, string>> = {};
  for (const [colour, token] of Object.entries(THEME_TOKENS) as [ThemeColour, string][]) {
    const value = style.getPropertyValue(token).trim();
    if (value !== '') {
      theme[colour] = value;
    }
  }
  return theme;
}

function sizeOf(size: TerminalSize): TerminalSize {
  return { cols: size.cols, rows: size.rows };
}

function resizesOf(element: HTMLElement): Observable<void> {
  return new Observable<void>((subscriber) => {
    const Observer = element.ownerDocument.defaultView?.ResizeObserver;
    if (Observer === undefined) {
      return undefined;
    }
    const observer = new Observer(() => subscriber.next());
    observer.observe(element);
    return () => observer.disconnect();
  });
}
