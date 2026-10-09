const env = (name: string, fallback: string): string => process.env[name] ?? fallback;

export const ADMIN = {
  username: env('E2E_ADMIN_USER', 'admin'),
  password: env('E2E_ADMIN_PASSWORD', 'journey-admin-pass'),
};

export const SSH = {
  host: env('E2E_SSH_HOST', '127.0.0.1'),
  port: Number(env('E2E_SSH_PORT', '2222')),
  username: env('E2E_SSH_USER', 'root'),
  password: env('E2E_SSH_PASSWORD', 'deploy-password'),
  fingerprint: env('E2E_SSH_FINGERPRINT', 'SHA256:D2rcDvLqLvUVrqJt0lF5f4J1hqE4zE8fkAEGhprUiIY'),
  projectDir: env('E2E_SSH_PROJECT_DIR', '/srv/e2e-app'),
  python: env('E2E_SSH_PYTHON', '/srv/e2e-app/.venv/bin/python'),
  remoteBackupDir: env('E2E_SSH_REMOTE_BACKUP_DIR', '/var/backups/e2e-dbs'),
  envPath: env('E2E_SSH_ENV_PATH', '/srv/e2e-app/.env'),
  mediaDir: env('E2E_SSH_MEDIA_DIR', '/srv/e2e-app/media'),
  existingDir: env('E2E_SSH_EXISTING_DIR', '/var/backups/e2e-existing'),
  existingFiles: env('E2E_SSH_EXISTING_FILES', 'db-2026-09-30.sql.gz,db-2026-09-29.sql.gz').split(','),
};

export const ALLOWED_FOLDERS = [SSH.mediaDir, SSH.existingDir];

export const SSH_FS = env('E2E_SSH_FS', '/');

export const DATA_DIR = env('E2E_DATA_DIR', '');

export const SETUP_TOKEN = process.env['E2E_SETUP_TOKEN'] ?? null;

export const SCREENSHOT_DIR = env('E2E_SCREENSHOT_DIR', 'test-results/journeys');
