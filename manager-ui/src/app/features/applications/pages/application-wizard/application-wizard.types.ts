import type { DraftField } from '../../components/settings-fields/settings-fields.types';

export type WizardStep = 'folder' | 'discovery' | 'review' | 'check' | 'passphrase' | 'backup';

export type WizardField = DraftField | 'folder';
