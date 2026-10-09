export interface ServerRecord {
  id: string;
  name: string;
  host_key_fingerprint: string;
}

export interface Page<T> {
  count: number;
  results: T[];
}

export interface BackupRecord {
  id: string;
  name: string;
  kind: string;
  validation: string;
}

export interface JobStarted {
  activity: number;
}

export interface PlanRecord {
  id: string;
  name: string;
}

export interface ActivityRecord {
  id: number;
  action: string;
  status: string;
  target: string;
  error_code: string;
  server_name: string | null;
}
