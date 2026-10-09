export type AboutCommandKey = 'export' | 'exportWithBackups' | 'import';

export interface AboutCommand {
  readonly key: AboutCommandKey;
  readonly text: string;
}
