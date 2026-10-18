import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { TERMINAL_SCREENS } from './terminal-screens';
import { TERMINAL_FIT_DEBOUNCE_MS, TerminalView } from './terminal-view';
import type { TerminalSize } from './terminal-view.types';
import { FakeTerminalScreens } from './testing/fake-terminal-screens';

class FakeResizeObserver {
  static readonly observers: FakeResizeObserver[] = [];
  readonly observed: Element[] = [];
  disconnected = false;

  constructor(private readonly callback: () => void) {
    FakeResizeObserver.observers.push(this);
  }

  observe(element: Element): void {
    this.observed.push(element);
  }

  disconnect(): void {
    this.disconnected = true;
  }

  fire(): void {
    this.callback();
  }
}

const TOKENS: Readonly<Record<string, string>> = {
  '--app-color-surface': '#ffffff',
  '--app-color-on-surface': '#182030',
  '--app-color-primary': '#1d5bd6',
  '--app-color-danger': '#b42318',
  '--app-color-on-surface-variant': '#52607a',
  '--app-font-mono': 'ui-monospace, monospace',
};

describe('TerminalView', () => {
  let fixture: ComponentFixture<TerminalView>;
  let screens: FakeTerminalScreens;
  let typed: string[];
  let sizes: TerminalSize[];
  const resizeObserverBefore = Object.getOwnPropertyDescriptor(window, 'ResizeObserver');

  const render = async (interactive = true): Promise<void> => {
    fixture = TestBed.createComponent(TerminalView);
    fixture.componentRef.setInput('label', 'Shell for web-1');
    fixture.componentRef.setInput('tooMuchOutput', 'Too much output');
    fixture.componentRef.setInput('interactive', interactive);
    fixture.componentInstance.typed.subscribe((data) => typed.push(data));
    fixture.componentInstance.resized.subscribe((size) => sizes.push(size));
    fixture.detectChanges();
    await fixture.whenStable();
  };

  const frame = (): HTMLElement => {
    const element = (fixture.nativeElement as HTMLElement).querySelector<HTMLElement>('.terminal-view__frame');
    if (element === null) {
      throw new Error('The frame is not on screen.');
    }
    return element;
  };

  beforeEach(() => {
    FakeResizeObserver.observers.length = 0;
    Object.defineProperty(window, 'ResizeObserver', { value: FakeResizeObserver, configurable: true, writable: true });
    for (const [token, value] of Object.entries(TOKENS)) {
      document.documentElement.style.setProperty(token, value);
    }
    screens = new FakeTerminalScreens();
    typed = [];
    sizes = [];
    TestBed.configureTestingModule({ providers: [{ provide: TERMINAL_SCREENS, useValue: screens }] });
  });

  afterEach(() => {
    vi.useRealTimers();
    TestBed.resetTestingModule();
    for (const token of Object.keys(TOKENS)) {
      document.documentElement.style.removeProperty(token);
    }
    if (resizeObserverBefore === undefined) {
      Reflect.deleteProperty(window, 'ResizeObserver');
    } else {
      Object.defineProperty(window, 'ResizeObserver', resizeObserverBefore);
    }
  });

  it('opens one screen-reader terminal in a left-to-right frame, labelled in the page language', async () => {
    await render();

    expect(screens.screens).toHaveLength(1);
    const screen = screens.screen;
    expect(screen.options.screenReaderMode).toBe(true);
    expect(screen.parent).toBe(frame());
    expect(frame().getAttribute('dir')).toBe('ltr');
    expect(frame().getAttribute('role')).toBe('group');
    expect(frame().getAttribute('aria-label')).toBe('Shell for web-1');
    expect(screens.strings).toEqual({ promptLabel: 'Shell for web-1', tooMuchOutput: 'Too much output' });
    expect(screen.textarea?.getAttribute('aria-label')).toBe('Shell for web-1');
  });

  it('takes its colours and its font from the tokens, never a colour of its own', async () => {
    await render();

    const theme = screens.screen.options.theme;
    expect(theme?.background).toBe('#ffffff');
    expect(theme?.foreground).toBe('#182030');
    expect(theme?.cursor).toBe('#1d5bd6');
    expect(theme?.red).toBe('#b42318');
    expect(theme?.white).toBe('#52607a');
    expect(theme?.brightWhite).toBe('#182030');
    expect(Object.values(theme ?? {}).every((colour) => Object.values(TOKENS).includes(colour as string))).toBe(true);
    expect(screens.screen.options.fontFamily).toBe('ui-monospace, monospace');
  });

  it('relabels the input when the language changes', async () => {
    await render();

    fixture.componentRef.setInput('label', 'صدفة web-1');
    fixture.detectChanges();
    await fixture.whenStable();

    expect(screens.screen.textarea?.getAttribute('aria-label')).toBe('صدفة web-1');
    expect(screens.strings.promptLabel).toBe('صدفة web-1');
  });

  it('fits itself once open and says its size', async () => {
    await render();

    expect(screens.fitter.fits).toBe(1);
    expect(sizes).toEqual([{ cols: 80, rows: 24 }]);
  });

  it('refits when its frame changes size, once the changes settle, and says the new size', async () => {
    await render();
    vi.useFakeTimers();
    const [observer] = FakeResizeObserver.observers;
    expect(observer.observed).toEqual([frame()]);
    screens.fitter.fitsTo = { cols: 132, rows: 40 };

    observer.fire();
    observer.fire();
    vi.advanceTimersByTime(TERMINAL_FIT_DEBOUNCE_MS - 1);
    expect(screens.fitter.fits).toBe(1);
    vi.advanceTimersByTime(1);

    expect(screens.fitter.fits).toBe(2);
    expect(sizes).toEqual([
      { cols: 80, rows: 24 },
      { cols: 132, rows: 40 },
    ]);
  });

  it('passes on what is typed', async () => {
    await render();

    screens.screen.type('ls -la\r');

    expect(typed).toEqual(['ls -la\r']);
  });

  it('takes no keystrokes while it is not interactive, and takes them again once it is', async () => {
    await render(false);
    expect(screens.screen.options.disableStdin).toBe(true);

    fixture.componentRef.setInput('interactive', true);
    fixture.detectChanges();
    await fixture.whenStable();

    expect(screens.screen.options.disableStdin).toBe(false);
  });

  it('writes bytes, clears and takes focus when asked', async () => {
    await render();
    const view = fixture.componentInstance;

    view.write(new TextEncoder().encode('hello\r\n'));
    view.clear();
    view.focus();

    expect(screens.screen.text()).toBe('hello\r\n');
    expect(screens.screen.resets).toBe(1);
    expect(screens.screen.focuses).toBe(1);
  });

  it('disposes the terminal and stops watching its size when it goes', async () => {
    await render();
    const [observer] = FakeResizeObserver.observers;

    fixture.destroy();

    expect(screens.screen.disposed).toBe(true);
    expect(observer.disconnected).toBe(true);
  });

  it('opens without watching its size where the browser cannot', async () => {
    Reflect.deleteProperty(window, 'ResizeObserver');
    await render();

    expect(screens.screen.parent).toBe(frame());
    expect(sizes).toEqual([{ cols: 80, rows: 24 }]);
  });
});
