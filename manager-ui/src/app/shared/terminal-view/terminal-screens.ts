import { InjectionToken } from '@angular/core';
import { FitAddon } from '@xterm/addon-fit';
import { Terminal, type ILocalizableStrings, type ITerminalOptions } from '@xterm/xterm';

import type { TerminalScreenParts, TerminalScreens } from './terminal-view.types';

export const TERMINAL_SCREENS = new InjectionToken<TerminalScreens>('TERMINAL_SCREENS', {
  providedIn: 'root',
  factory: () => ({ create, localize }),
});

function create(options: ITerminalOptions): TerminalScreenParts {
  const screen = new Terminal(options);
  const fitter = new FitAddon();
  screen.loadAddon(fitter);
  return { screen, fitter };
}

function localize(strings: ILocalizableStrings): void {
  Terminal.strings.promptLabel = strings.promptLabel;
  Terminal.strings.tooMuchOutput = strings.tooMuchOutput;
}
