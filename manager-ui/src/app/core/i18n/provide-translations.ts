import { inject, provideEnvironmentInitializer, type EnvironmentProviders } from '@angular/core';

import { LocaleStore } from './locale.store';
import type { TranslationBundle } from './locale.types';

export function provideTranslations(
  en: TranslationBundle,
  ar: TranslationBundle,
): EnvironmentProviders {
  return provideEnvironmentInitializer(() => inject(LocaleStore).register({ en, ar }));
}
