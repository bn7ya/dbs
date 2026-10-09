import { definePreset } from '@primeuix/themes';
import Aura from '@primeuix/themes/aura';

export const AppPreset = definePreset(Aura, {
  primitive: {
    borderRadius: {
      none: '0',
      xs: 'var(--app-radius-sm)',
      sm: 'var(--app-radius-md)',
      md: 'var(--app-radius-md)',
      lg: 'var(--app-radius-lg)',
      xl: 'var(--app-radius-lg)',
    },
  },
  semantic: {
    primary: {
      50: '#fbf7ea',
      100: '#f5ebc9',
      200: '#ecd796',
      300: '#e2bd62',
      400: '#c99f3d',
      500: '#a6811f',
      600: '#7a5c12',
      700: '#62480e',
      800: '#4d390d',
      900: '#3d2e0d',
      950: '#241a00',
    },
    colorScheme: {
      light: {
        primary: {
          color: '{primary.600}',
          contrastColor: '#ffffff',
          hoverColor: '{primary.700}',
          activeColor: '{primary.800}',
        },
      },
      dark: {
        primary: {
          color: '{primary.300}',
          contrastColor: '#241a00',
          hoverColor: '{primary.200}',
          activeColor: '{primary.100}',
        },
      },
    },
  },
});
