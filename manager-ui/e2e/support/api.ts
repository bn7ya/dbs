import { expect, request, type APIRequestContext, type Cookie } from '@playwright/test';
import type {
  ActivityRecord,
  ApplicationRecord,
  BackupRecord,
  JobStarted,
  Page,
  PlanRecord,
  ServerRecord,
} from './api.types';
import { ADMIN, ALLOWED_FOLDERS, SSH } from './config';
import { freshCode } from './totp';

const sessions = new Map<string, Api>();

export class Api {
  private constructor(
    private readonly http: APIRequestContext,
    private readonly csrf: string,
  ) {}

  // One session per worker and account, renewed when something signed it out.
  static async signIn(baseURL: string, user = ADMIN): Promise<Api> {
    const key = `${baseURL} ${user.username}`;
    const kept = sessions.get(key);
    if (kept && (await kept.http.get('/api/auth/me/')).ok()) return kept;
    const api = await Api.freshSession(baseURL, user);
    sessions.set(key, api);
    return api;
  }

  private static async freshSession(baseURL: string, user: { username: string; password: string }): Promise<Api> {
    const http = await request.newContext({ baseURL });
    await http.get('/api/auth/csrf/');
    const csrf = await csrfToken(http, baseURL);
    const login = await http.post('/api/auth/login/', {
      headers: { 'X-CSRFToken': csrf },
      data: { username: user.username, password: user.password },
    });
    if (!login.ok()) {
      throw new Error(`API sign-in failed: ${login.status()} ${await login.text()}`);
    }
    const second = await http.post('/api/auth/two-factor/', {
      headers: { 'X-CSRFToken': csrf },
      data: { code: await freshCode() },
    });
    if (!second.ok()) {
      throw new Error(`API two-factor sign-in failed: ${second.status()} ${await second.text()}`);
    }
    return new Api(http, await csrfToken(http, baseURL));
  }

  async cookies(): Promise<Cookie[]> {
    return (await this.http.storageState()).cookies;
  }

  async createServer(name: string): Promise<ServerRecord> {
    const key = await this.post<{ line: string }>('/api/servers/fingerprint/', {
      host: SSH.host,
      port: SSH.port,
    });
    return this.post<ServerRecord>('/api/servers/', {
      name,
      host: SSH.host,
      port: SSH.port,
      username: SSH.username,
      auth_method: 'password',
      password: SSH.password,
      host_key: key.line,
    });
  }

  async createApplication(
    server: string,
    name: string,
    overrides: Record<string, unknown> = {},
  ): Promise<ApplicationRecord> {
    return this.post<ApplicationRecord>('/api/applications/', {
      server,
      name,
      account_password: ADMIN.password,
      kind: 'host',
      project_dir: SSH.projectDir,
      python_path: SSH.python,
      manage_path: 'manage.py',
      settings_module: 'shop.settings',
      remote_backup_dir: SSH.remoteBackupDir,
      file_roots: ALLOWED_FOLDERS,
      env_path: SSH.envPath,
      ...overrides,
    });
  }

  async createServerWithApplication(
    name: string,
    overrides: Record<string, unknown> = {},
  ): Promise<{ server: ServerRecord; application: ApplicationRecord }> {
    const server = await this.createServer(`${name} server`);
    const application = await this.createApplication(server.id, name, overrides);
    return { server, application };
  }

  async application(id: string): Promise<ApplicationRecord> {
    return this.get<ApplicationRecord>(`/api/applications/${id}/`);
  }

  async findServers(nameStartsWith: string): Promise<ServerRecord[]> {
    const page = await this.get<Page<ServerRecord>>(
      `/api/servers/?search=${encodeURIComponent(nameStartsWith)}&page_size=100`,
    );
    return page.results.filter((s) => s.name.startsWith(nameStartsWith));
  }

  async applicationsOf(server: string): Promise<ApplicationRecord[]> {
    return (await this.get<Page<ApplicationRecord>>(`/api/applications/?server=${server}&page_size=100`)).results;
  }

  async deleteApplication(id: string): Promise<void> {
    for (const plan of await this.plans(id)) {
      await this.delete(`/api/backups/plans/${plan.id}/`);
    }
    for (const file of await this.backups(id)) {
      await this.delete(`/api/backups/${file.id}/`, { account_password: ADMIN.password });
    }
    await this.delete(`/api/applications/${id}/`, { account_password: ADMIN.password });
  }

  async deleteServer(id: string): Promise<void> {
    for (const application of await this.applicationsOf(id)) {
      await this.deleteApplication(application.id);
    }
    await this.delete(`/api/servers/${id}/`, { account_password: ADMIN.password });
  }

  async deleteServersNamed(prefix: string): Promise<void> {
    for (const server of await this.findServers(prefix)) await this.deleteServer(server.id);
  }

  async capturePassphrase(application: string): Promise<void> {
    await this.post<unknown>(`/api/applications/${application}/passphrase/capture/`, {});
  }

  async takeBackup(application: string): Promise<ActivityRecord> {
    const { activity } = await this.post<JobStarted>('/api/backups/take/', { application });
    const read = () => this.get<ActivityRecord>(`/api/activity/${activity}/`);
    await expect.poll(async () => (await read()).status, { timeout: 180_000 }).toMatch(/^(succeeded|failed)$/);
    return read();
  }

  async backups(application: string): Promise<BackupRecord[]> {
    return (await this.get<Page<BackupRecord>>(`/api/backups/?application=${application}&page_size=100`)).results;
  }

  async plans(application: string): Promise<PlanRecord[]> {
    return (await this.get<Page<PlanRecord>>(`/api/backups/plans/?application=${application}&page_size=100`))
      .results;
  }

  async closeTerminals(): Promise<void> {
    const open = await this.get<{ results: { id: string }[] }>('/api/terminals/');
    for (const terminal of open.results) await this.delete(`/api/terminals/${terminal.id}/`);
  }

  private async get<T>(path: string): Promise<T> {
    const response = await this.http.get(path);
    if (!response.ok()) throw new Error(`GET ${path}: ${response.status()} ${await response.text()}`);
    return (await response.json()) as T;
  }

  private async post<T>(path: string, data: unknown): Promise<T> {
    const response = await this.http.post(path, { headers: { 'X-CSRFToken': this.csrf }, data });
    if (!response.ok()) throw new Error(`POST ${path}: ${response.status()} ${await response.text()}`);
    return (await response.json()) as T;
  }

  private async delete(path: string, data?: Record<string, string>): Promise<void> {
    const response = await this.http.delete(path, { headers: { 'X-CSRFToken': this.csrf }, data });
    if (!response.ok() && response.status() !== 404) {
      throw new Error(`DELETE ${path}: ${response.status()} ${await response.text()}`);
    }
  }
}

async function csrfToken(http: APIRequestContext, baseURL: string): Promise<string> {
  const cookies = await http.storageState();
  const origin = new URL(baseURL).hostname;
  const token = cookies.cookies.find((c) => c.name === 'csrftoken' && origin.endsWith(c.domain.replace(/^\./, '')));
  if (!token) throw new Error('No csrftoken cookie after GET /api/auth/csrf/');
  return token.value;
}
