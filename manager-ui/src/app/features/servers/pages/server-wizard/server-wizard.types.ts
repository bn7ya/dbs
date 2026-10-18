export type SignInChoice = 'generate' | 'key' | 'password';

export type WizardStep = 'address' | 'hostKey' | 'signIn' | 'check' | 'done';

export interface WizardDraft {
  readonly name: string;
  readonly host: string;
  readonly port: number | null;
  readonly username: string;
  readonly sign_in: SignInChoice;
  readonly private_key: string;
  readonly key_passphrase: string;
  readonly password: string;
}

export type WizardField = keyof WizardDraft | 'host_key';
