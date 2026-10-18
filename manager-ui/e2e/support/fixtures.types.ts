import type { Locator, Page } from '@playwright/test';
import type { CopyKey, Lang } from './copy.types';

export interface Journey {
  lang: Lang;
  dir: 'ltr' | 'rtl';
  t: (key: CopyKey) => string;
  say: (key: CopyKey, values: Record<string, string>) => string;
  matching: (key: CopyKey, name: string) => RegExp;
  signIn: (page: Page, user?: { username: string; password: string }) => Promise<void>;
  shot: (page: Page, name: string) => Promise<void>;
  toast: (page: Page, key: CopyKey) => Locator;
  shown: (scope: Page | Locator, text: string) => Locator;
  signOut: (page: Page, user?: { username: string; password: string }) => Promise<void>;
  dismissToasts: (page: Page) => Promise<void>;
}
