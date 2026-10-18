export interface ConsoleRequest {
  readonly line: string;
  readonly password?: string;
}

export interface ConsoleResult {
  readonly exit_code: number;
  readonly output: string;
  readonly activities: readonly number[];
  readonly password_required: boolean;
  readonly error_code: string;
}
