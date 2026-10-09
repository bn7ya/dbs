import type { Locator, Page } from '@playwright/test';
import type { CopyKey, Lang } from './copy.types';

export interface Journey {
  lang: Lang;
  dir: 'ltr' | 'rtl';
  t: (key: CopyKey) => string;
  named: (action: CopyKey, target: string, suffix?: CopyKey) => string;
  unique: (what: string) => string;
  signIn: (page: Page, user?: { username: string; password: string }) => Promise<void>;
  shot: (page: Page, name: string) => Promise<void>;
  toast: (page: Page, key: CopyKey) => Locator;
  shown: (scope: Page | Locator, text: string) => Locator;
  dismissToasts: (page: Page) => Promise<void>;
}
