import type { IDisposable, ILocalizableStrings, ITerminalOptions, ITheme } from '@xterm/xterm';

export interface TerminalSize {
  readonly cols: number;
  readonly rows: number;
}

export interface TerminalScreen {
  readonly cols: number;
  readonly rows: number;
  readonly options: ITerminalOptions;
  readonly textarea: HTMLTextAreaElement | undefined;
  open(parent: HTMLElement): void;
  write(data: Uint8Array): void;
  reset(): void;
  focus(): void;
  onData(listener: (data: string) => void): IDisposable;
  onResize(listener: (size: TerminalSize) => void): IDisposable;
  dispose(): void;
}

export interface TerminalFitter {
  fit(): void;
}

export interface TerminalScreenParts {
  readonly screen: TerminalScreen;
  readonly fitter: TerminalFitter;
}

export interface TerminalScreens {
  create(options: ITerminalOptions): TerminalScreenParts;
  localize(strings: ILocalizableStrings): void;
}

export type ThemeColour = Exclude<keyof ITheme, 'extendedAnsi'>;
