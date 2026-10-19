import { describe, expect, it } from 'vitest';

import { formatIn, isoOf, momentProblem, partsOf, shownZone, timeZoneNames, zoneNamed } from './zoned-time';

const DAY = 24 * 60 * 60 * 1000;

describe('zoned time', () => {
  it("writes a date and a time picked in the browser as that wall clock in the plan's zone, with its offset", () => {
    const moment = (zone: string, month: number, day: number, hours: number, minutes = 0) =>
      isoOf({ day: new Date(2026, month, day), time: new Date(2026, month, day, hours, minutes) }, zone);

    expect(moment('Europe/Berlin', 9, 20, 2, 30)).toBe('2026-10-20T02:30:00+02:00');
    expect(moment('Europe/Berlin', 11, 20, 2, 30)).toBe('2026-12-20T02:30:00+01:00');
    expect(moment('Asia/Kolkata', 9, 20, 23, 45)).toBe('2026-10-20T23:45:00+05:30');
    expect(moment('America/New_York', 9, 20, 9)).toBe('2026-10-20T09:00:00-04:00');
    expect(moment('UTC', 9, 20, 9)).toBe('2026-10-20T09:00:00+00:00');
  });

  it('moves a time the clocks skip to the hour after, and needs both parts', () => {
    expect(isoOf({ day: new Date(2026, 2, 29), time: new Date(2026, 2, 29, 2, 30) }, 'Europe/Berlin')).toBe(
      '2026-03-29T03:30:00+02:00',
    );
    expect(isoOf({ day: new Date(2026, 2, 29), time: null }, 'Europe/Berlin')).toBeNull();
    expect(isoOf({ day: null, time: new Date() }, 'Europe/Berlin')).toBeNull();
  });

  it("reads a moment back as the zone's wall clock on browser dates", () => {
    const { day, time } = partsOf('2026-10-20T00:30:45.120Z', 'Europe/Berlin');

    expect([day?.getFullYear(), day?.getMonth(), day?.getDate()]).toEqual([2026, 9, 20]);
    expect([time?.getHours(), time?.getMinutes()]).toEqual([2, 30]);
    expect(partsOf(null, 'Europe/Berlin')).toEqual({ day: null, time: null });
  });

  it('asks for the missing part, and for a moment after now and within a year', () => {
    const now = Date.now();
    const at = (instant: number) => {
      const day = new Date(instant);
      return { day, time: day };
    };

    expect(momentProblem({ day: null, time: null }, 'UTC', now)).toBeNull();
    expect(momentProblem({ day: new Date(), time: null }, 'UTC', now)).toEqual({ part: 'time', code: 'required' });
    expect(momentProblem({ day: null, time: new Date() }, 'UTC', now)).toEqual({ part: 'day', code: 'required' });
    expect(momentProblem(at(now - DAY), 'UTC', now)).toEqual({ part: 'day', code: 'invalid_moment' });
    expect(momentProblem(at(now + 400 * DAY), 'UTC', now)).toEqual({ part: 'day', code: 'invalid_moment' });
    expect(momentProblem(at(now + 2 * DAY), 'UTC', now)).toBeNull();
  });

  it('formats a moment in a zone with Latin digits, and in UTC for a zone it does not know', () => {
    const spaced = (text: string) => text.replace(/\s/g, ' ');

    expect(spaced(formatIn('en', '2026-10-20T00:30:00Z', 'Asia/Riyadh'))).toBe('Oct 20, 2026, 3:30 AM');
    expect(formatIn('ar', '2026-10-20T00:30:00Z', 'Asia/Riyadh')).toMatch(/3:30/);
    expect(spaced(formatIn('en', '2026-10-20T00:30:00Z', 'Nowhere/Land'))).toBe('Oct 20, 2026, 12:30 AM');
    expect(shownZone('Nowhere/Land')).toBe('UTC');
  });

  it('takes any zone the browser knows, by its older or newer name, fixing only its case', () => {
    expect(zoneNamed(' europe/berlin ')).toBe('Europe/Berlin');
    expect(zoneNamed('Asia/Kolkata')).toBe('Asia/Kolkata');
    expect(zoneNamed('Asia/Calcutta')).toBe('Asia/Calcutta');
    expect(zoneNamed('utc')).toBe('UTC');
    expect(zoneNamed('Mars/Olympus')).toBeNull();
    expect(zoneNamed('  ')).toBeNull();
  });

  it('offers every zone the browser knows, UTC and the ones given, each once', () => {
    const zones = timeZoneNames('UTC', 'Asia/Calcutta', 'Nowhere/Land');

    expect(zones).toContain('UTC');
    expect(zones).toContain('Europe/Berlin');
    expect(zones).toContain('Asia/Calcutta');
    expect(zones).not.toContain('Nowhere/Land');
    expect(new Set(zones).size).toBe(zones.length);
  });
});
