import { mkdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';

export async function acquireLock(name: string, staleAfterMs = 10 * 60_000): Promise<() => void> {
  const dir = join(tmpdir(), `dbs-e2e-${name}.lock`);
  const deadline = Date.now() + staleAfterMs;
  for (;;) {
    try {
      mkdirSync(dir);
      return () => rmSync(dir, { recursive: true, force: true });
    } catch {
      const age = Date.now() - statSync(dir, { throwIfNoEntry: false })?.mtimeMs!;
      if (age > staleAfterMs) rmSync(dir, { recursive: true, force: true });
      if (Date.now() > deadline) throw new Error(`Gave up waiting for the ${name} lock`);
      await sleep(500);
    }
  }
}
