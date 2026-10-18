import type { Job } from '@core/jobs/job.types';
import type { ConsoleResult } from '../data/console.types';

export const LISTED: ConsoleResult = {
  exit_code: 0,
  output: 'NAME   HOST\nweb-1  10.0.0.5\n',
  activities: [],
  password_required: false,
  error_code: '',
};

export const HELP: ConsoleResult = {
  exit_code: 0,
  output: 'usage: django_dbs [-h] COMMAND ...\n',
  activities: [],
  password_required: false,
  error_code: '',
};

export const NEEDS_PASSWORD: ConsoleResult = {
  exit_code: 1,
  output: '',
  activities: [],
  password_required: true,
  error_code: '',
};

export const WRONG_PASSWORD: ConsoleResult = {
  exit_code: 1,
  output: 'django_dbs: That password is not right.\n',
  activities: [],
  password_required: false,
  error_code: 'invalid_password',
};

export const REFUSED_ROLE: ConsoleResult = {
  exit_code: 1,
  output: 'django_dbs: This needs the admin role.\n',
  activities: [],
  password_required: false,
  error_code: 'role_required',
};

export const ACTIVITY_ID = 42;

export const STARTED: ConsoleResult = {
  exit_code: 0,
  output: `Started; follow it as activity ${ACTIVITY_ID}.\n`,
  activities: [ACTIVITY_ID],
  password_required: false,
  error_code: '',
};

export const RUNNING_JOB: Job = {
  id: ACTIVITY_ID,
  action: 'backup.take',
  status: 'running',
  detail: {},
  error_code: '',
  finished_at: null,
};

export const FAILED_JOB: Job = {
  ...RUNNING_JOB,
  status: 'failed',
  error_code: 'ssh_unreachable',
  finished_at: '2026-10-18T12:01:00Z',
};
