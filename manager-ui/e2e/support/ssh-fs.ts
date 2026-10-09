import { existsSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync, appendFileSync } from 'node:fs';
import { join } from 'node:path';
import { SSH_FS } from './config';

export const remoteReachable = SSH_FS !== '';

const local = (remotePath: string): string => join(SSH_FS, remotePath);

export function readRemote(remotePath: string): Buffer | null {
  if (!remoteReachable) return null;
  return readFileSync(local(remotePath));
}

export function writeRemote(remotePath: string, content: Buffer | string): void {
  if (!remoteReachable) return;
  writeFileSync(local(remotePath), content);
}

export function appendRemote(remotePath: string, content: string): void {
  if (!remoteReachable) return;
  appendFileSync(local(remotePath), content);
}

export function remoteExists(remotePath: string): boolean | null {
  if (!remoteReachable) return null;
  return existsSync(local(remotePath));
}

export function listRemote(remotePath: string): string[] | null {
  if (!remoteReachable) return null;
  return readdirSync(local(remotePath)).sort();
}

export function remoteMtime(remotePath: string): number | null {
  if (!remoteReachable) return null;
  return statSync(local(remotePath)).mtimeMs;
}

export function folderSnapshot(remotePath: string): { restore(): string[] } {
  const before = new Set(listRemote(remotePath) ?? []);
  return {
    restore(): string[] {
      const removed: string[] = [];
      for (const name of listRemote(remotePath) ?? []) {
        if (before.has(name)) continue;
        rmSync(local(join(remotePath, name)), { recursive: true, force: true });
        removed.push(name);
      }
      return removed;
    },
  };
}

export function scratchFile(dir: string, name: string, content: string): string {
  mkdirSync(dir, { recursive: true });
  const path = join(dir, name);
  writeFileSync(path, content);
  return path;
}
