import { InjectionToken } from '@angular/core';

import type { MomentParts, MomentProblem, WallClock } from './zoned-time.types';

const UTC = 'UTC';

const MINUTE_MS = 60_000;

// The backend takes a moment after now and at most 366 days ahead.
const FARTHEST_AHEAD_MS = 366 * 24 * 60 * MINUTE_MS;

export const LOCAL_TIME_ZONE = new InjectionToken<string>('LOCAL_TIME_ZONE', {
  providedIn: 'root',
  factory: () => Intl.DateTimeFormat().resolvedOptions().timeZone || UTC,
});

function isTimeZone(zone: string): boolean {
  if (zone === '') {
    return false;
  }
  try {
    return new Intl.DateTimeFormat('en-US', { timeZone: zone }).resolvedOptions().timeZone !== '';
  } catch {
    return false;
  }
}

// Browsers list some zones by older names (Asia/Calcutta), so any name the browser knows is taken; only its case is fixed.
export function zoneNamed(text: string): string | null {
  const name = text.trim();
  if (!isTimeZone(name)) {
    return null;
  }
  const resolved = new Intl.DateTimeFormat('en-US', { timeZone: name }).resolvedOptions().timeZone;
  return resolved.toLowerCase() === name.toLowerCase() ? resolved : name;
}

export function timeZoneNames(...known: readonly string[]): readonly string[] {
  const names = new Set([UTC, ...Intl.supportedValuesOf('timeZone'), ...known.filter(isTimeZone)]);
  return [...names].sort();
}

export function shownZone(zone: string): string {
  return isTimeZone(zone) ? zone : UTC;
}

export function formatIn(locale: string, moment: string, zone: string): string {
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
    calendar: 'gregory',
    numberingSystem: 'latn',
    timeZone: shownZone(zone),
  }).format(new Date(moment));
}

function momentOf({ day, time }: MomentParts, zone: string): number | null {
  if (day === null || time === null) {
    return null;
  }
  return instantOf(
    {
      year: day.getFullYear(),
      month: day.getMonth(),
      day: day.getDate(),
      hours: time.getHours(),
      minutes: time.getMinutes(),
    },
    zone,
  );
}

// The datepicker and the timepicker read the browser's clock, so the zone's wall clock is set on local dates.
export function partsOf(moment: string | null, zone: string): MomentParts {
  if (moment === null) {
    return { day: null, time: null };
  }
  const clock = wallClockIn(Date.parse(moment), zone);
  return {
    day: new Date(clock.year, clock.month, clock.day),
    time: new Date(clock.year, clock.month, clock.day, clock.hours, clock.minutes),
  };
}

export function momentProblem(parts: MomentParts, zone: string, now: number): MomentProblem | null {
  if (parts.day === null && parts.time === null) {
    return null;
  }
  if (parts.day === null) {
    return { part: 'day', code: 'required' };
  }
  if (parts.time === null) {
    return { part: 'time', code: 'required' };
  }
  const moment = momentOf(parts, zone) ?? now;
  return moment > now && moment <= now + FARTHEST_AHEAD_MS ? null : { part: 'day', code: 'invalid_moment' };
}

export function isoOf(parts: MomentParts, zone: string): string | null {
  const moment = momentOf(parts, zone);
  return moment === null ? null : isoIn(moment, zone);
}

function isoIn(instant: number, zone: string): string {
  const offset = offsetMinutes(instant, zone);
  const clock = wallClockIn(instant, zone);
  const date = `${pad(clock.year, 4)}-${pad(clock.month + 1)}-${pad(clock.day)}`;
  return `${date}T${pad(clock.hours)}:${pad(clock.minutes)}:00${offsetText(offset)}`;
}

function instantOf(clock: WallClock, zone: string): number {
  const guess = utcOf(clock);
  const first = offsetMinutes(guess, zone);
  const instant = guess - first * MINUTE_MS;
  const second = offsetMinutes(instant, zone);
  return second === first ? instant : guess - second * MINUTE_MS;
}

function wallClockIn(instant: number, zone: string): WallClock {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: shownZone(zone),
    hourCycle: 'h23',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    calendar: 'gregory',
    numberingSystem: 'latn',
  }).formatToParts(new Date(instant));
  const part = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((each) => each.type === type)?.value ?? 0);
  return {
    year: part('year'),
    month: part('month') - 1,
    day: part('day'),
    hours: part('hour'),
    minutes: part('minute'),
  };
}

function offsetMinutes(instant: number, zone: string): number {
  const whole = Math.floor(instant / MINUTE_MS) * MINUTE_MS;
  return (utcOf(wallClockIn(whole, zone)) - whole) / MINUTE_MS;
}

function utcOf(clock: WallClock): number {
  return Date.UTC(clock.year, clock.month, clock.day, clock.hours, clock.minutes);
}

function offsetText(minutes: number): string {
  const absolute = Math.abs(minutes);
  return `${minutes < 0 ? '-' : '+'}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
}

function pad(value: number, width = 2): string {
  return String(value).padStart(width, '0');
}
