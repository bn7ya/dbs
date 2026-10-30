export type RunAttempt = 'rehearsal' | 'real';

export interface RunRequest {
  readonly rehearsal: boolean;
  readonly password: string;
  readonly confirm_name: string;
}
