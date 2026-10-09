import { expect, request, type APIRequestContext } from '@playwright/test';
import type { ActivityRecord, BackupRecord, JobStarted, Page, PlanRecord, ServerRecord } from './api.types';
import { ADMIN, ALLOWED_FOLDERS, SSH } from './config';


export class Api {
  private constructor(
    private readonly http: APIRequestContext,
    private readonly csrf: string,
  ) {}

  static async signIn(baseURL: string, user = ADMIN): Promise<Api> {
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
    return new Api(http, await csrfToken(http, baseURL));
  }

  async dispose(): Promise<void> {
    await this.http.dispose();
  }

  async createServer(name: string, overrides: Record<string, unknown> = {}): Promise<ServerRecord> {
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
      project_dir: SSH.projectDir,
      python_path: SSH.python,
      manage_path: 'manage.py',
      settings_module: '',
      remote_backup_dir: SSH.remoteBackupDir,
      file_roots: ALLOWED_FOLDERS,
      env_path: SSH.envPath,
      ...overrides,
    });
  }

  async findServers(nameStartsWith: string): Promise<ServerRecord[]> {
    const page = await this.get<Page<ServerRecord>>(
      `/api/servers/?search=${encodeURIComponent(nameStartsWith)}&page_size=100`,
    );
    return page.results.filter((s) => s.name.startsWith(nameStartsWith));
  }

  async deleteServer(id: string): Promise<void> {
    for (const plan of await this.plans(id)) {
      await this.delete(`/api/backups/plans/${plan.id}/`);
    }
    for (const file of await this.backups(id)) {
      await this.delete(`/api/backups/${file.id}/`);
    }
    await this.delete(`/api/servers/${id}/`);
  }

  async capturePassphrase(server: string): Promise<void> {
    await this.post<unknown>(`/api/servers/${server}/passphrase/capture/`, {});
  }

  async takeBackup(server: string): Promise<ActivityRecord> {
    const { activity } = await this.post<JobStarted>('/api/backups/take/', { server });
    const read = () => this.get<ActivityRecord>(`/api/activity/${activity}/`);
    await expect.poll(async () => (await read()).status, { timeout: 180_000 }).toMatch(/^(succeeded|failed)$/);
    return read();
  }

  async backups(server: string): Promise<BackupRecord[]> {
    return (await this.get<Page<BackupRecord>>(`/api/backups/?server=${server}&page_size=100`)).results;
  }

  async plans(server: string): Promise<PlanRecord[]> {
    return (await this.get<Page<PlanRecord>>(`/api/backups/plans/?server=${server}&page_size=100`)).results;
  }

  async activity(query: Record<string, string>): Promise<ActivityRecord[]> {
    const params = new URLSearchParams({ page_size: '100', ...query });
    return (await this.get<Page<ActivityRecord>>(`/api/activity/?${params.toString()}`)).results;
  }

  async status(method: 'get' | 'post' | 'delete', path: string): Promise<number> {
    const response = await this.http[method](path, { headers: { 'X-CSRFToken': this.csrf } });
    return response.status();
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

  private async delete(path: string): Promise<void> {
    const response = await this.http.delete(path, { headers: { 'X-CSRFToken': this.csrf } });
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
