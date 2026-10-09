export interface TimeStep {
  readonly unit: Intl.RelativeTimeFormatUnit;
  readonly seconds: number;
  readonly below: number;
}

const MINUTE = 60;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const MONTH = 30 * DAY;

export const TIME_STEPS: readonly TimeStep[] = [
  { unit: 'minute', seconds: MINUTE, below: HOUR },
  { unit: 'hour', seconds: HOUR, below: DAY },
  { unit: 'day', seconds: DAY, below: MONTH },
  { unit: 'month', seconds: MONTH, below: Number.POSITIVE_INFINITY },
];
