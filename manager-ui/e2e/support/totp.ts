import { createHmac } from 'node:crypto';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { DATA_DIR, TOTP_SECRET } from './config';
import { acquireLock } from './lock';

const PERIOD_MS = 30_000;
const DIGITS = 6;
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
const SECRET_FILE = join(DATA_DIR, 'e2e-admin.totp');
const STEP_FILE = join(DATA_DIR, 'e2e-admin.step');

function secretBytes(secret: string): Buffer {
  let bits = '';
  for (const character of secret.replace(/\s/g, '').toUpperCase()) {
    bits += ALPHABET.indexOf(character).toString(2).padStart(5, '0');
  }
  const bytes: number[] = [];
  for (let at = 0; at + 8 <= bits.length; at += 8) {
    bytes.push(parseInt(bits.slice(at, at + 8), 2));
  }
  return Buffer.from(bytes);
}

export function codeAt(secret: string, step: number): string {
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(step));
  const digest = createHmac('sha1', secretBytes(secret)).update(counter).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const number = digest.readUInt32BE(offset) & 0x7fffffff;
  return String(number % 10 ** DIGITS).padStart(DIGITS, '0');
}

export function saveSecret(secret: string): void {
  writeFileSync(SECRET_FILE, secret.replace(/\s/g, ''));
}

function adminSecret(): string {
  return TOTP_SECRET ?? readFileSync(SECRET_FILE, 'utf8').trim();
}

// The manager takes each code once, so every journey gets a step no other one has used.
export async function freshCode(): Promise<string> {
  const release = await acquireLock('totp');
  try {
    const last = existsSync(STEP_FILE) ? Number(readFileSync(STEP_FILE, 'utf8')) : 0;
    const current = Math.floor(Date.now() / PERIOD_MS);
    const step = Math.max(current, last + 1);
    if (step > current + 1) {
      await sleep((step - 1) * PERIOD_MS - Date.now() + 1_000);
    }
    writeFileSync(STEP_FILE, String(step));
    return codeAt(adminSecret(), step);
  } finally {
    release();
  }
}
