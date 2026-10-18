import type { IDisposable, ILocalizableStrings, ITerminalOptions } from '@xterm/xterm';

import type { TerminalFitter, TerminalScreen, TerminalScreenParts, TerminalScreens, TerminalSize } from '../terminal-view.types';

export class FakeTerminalScreen implements TerminalScreen {
  cols = 80;
  rows = 24;
  readonly options: ITerminalOptions;
  textarea: HTMLTextAreaElement | undefined;
  parent: HTMLElement | null = null;
  readonly written: Uint8Array[] = [];
  resets = 0;
  focuses = 0;
  disposed = false;
  private dataListener: ((data: string) => void) | null = null;
  private resizeListener: ((size: TerminalSize) => void) | null = null;

  constructor(
    options: ITerminalOptions,
    private readonly strings: () => ILocalizableStrings,
  ) {
    this.options = { ...options };
  }

  open(parent: HTMLElement): void {
    this.parent = parent;
    this.textarea = parent.ownerDocument.createElement('textarea');
    this.textarea.setAttribute('aria-label', this.strings().promptLabel);
    parent.append(this.textarea);
  }

  write(data: Uint8Array): void {
    this.written.push(data);
  }

  reset(): void {
    this.resets += 1;
  }

  focus(): void {
    this.focuses += 1;
  }

  onData(listener: (data: string) => void): IDisposable {
    this.dataListener = listener;
    return { dispose: () => (this.dataListener = null) };
  }

  onResize(listener: (size: TerminalSize) => void): IDisposable {
    this.resizeListener = listener;
    return { dispose: () => (this.resizeListener = null) };
  }

  dispose(): void {
    this.disposed = true;
  }

  type(data: string): void {
    this.dataListener?.(data);
  }

  resizeTo(size: TerminalSize): void {
    if (size.cols === this.cols && size.rows === this.rows) {
      return;
    }
    this.cols = size.cols;
    this.rows = size.rows;
    this.resizeListener?.(size);
  }

  text(): string {
    return this.written.map((bytes) => new TextDecoder().decode(bytes)).join('');
  }
}

export class FakeTerminalFitter implements TerminalFitter {
  fits = 0;
  fitsTo: TerminalSize | null = null;

  constructor(private readonly screen: FakeTerminalScreen) {}

  fit(): void {
    this.fits += 1;
    if (this.fitsTo !== null) {
      this.screen.resizeTo(this.fitsTo);
    }
  }
}

export class FakeTerminalScreens implements TerminalScreens {
  readonly screens: FakeTerminalScreen[] = [];
  readonly fitters: FakeTerminalFitter[] = [];
  strings: ILocalizableStrings = { promptLabel: '', tooMuchOutput: '' };

  create(options: ITerminalOptions): TerminalScreenParts {
    const screen = new FakeTerminalScreen(options, () => this.strings);
    const fitter = new FakeTerminalFitter(screen);
    this.screens.push(screen);
    this.fitters.push(fitter);
    return { screen, fitter };
  }

  localize(strings: ILocalizableStrings): void {
    this.strings = { ...strings };
  }

  get screen(): FakeTerminalScreen {
    const screen = this.screens.at(-1);
    if (screen === undefined) {
      throw new Error('No terminal screen was created.');
    }
    return screen;
  }

  get fitter(): FakeTerminalFitter {
    const fitter = this.fitters.at(-1);
    if (fitter === undefined) {
      throw new Error('No terminal screen was created.');
    }
    return fitter;
  }
}
