import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { StepsList } from './steps-list';
import type { ListedStep } from './steps-list.types';

const STEPS: readonly ListedStep[] = [
  { key: 'check', label: 'Check the application', status: 'succeeded', statusLabel: 'Done' },
  { key: 'git_pull-0', label: 'Pull the code', status: 'running', statusLabel: 'Running' },
  { key: 'git_pull-1', label: 'Pull the code', status: 'pending', statusLabel: 'Waiting' },
  { key: 'final_check', label: 'Check again', status: 'skipped', statusLabel: 'Skipped' },
];

describe('StepsList', () => {
  let fixture: ComponentFixture<StepsList>;

  const items = (): HTMLElement[] => {
    fixture.detectChanges();
    return Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('li'));
  };

  beforeEach(() => {
    fixture = TestBed.createComponent(StepsList);
  });

  afterEach(() => TestBed.resetTestingModule());

  it('lists every step in order, by its label, with its status as a word', () => {
    fixture.componentRef.setInput('steps', STEPS);

    expect(
      items().map((item) => [
        item.querySelector('span')?.textContent?.trim(),
        item.querySelector('app-status-tag')?.textContent?.trim(),
      ]),
    ).toEqual([
      ['Check the application', 'Done'],
      ['Pull the code', 'Running'],
      ['Pull the code', 'Waiting'],
      ['Check again', 'Skipped'],
    ]);
    expect((fixture.nativeElement as HTMLElement).querySelector('ol')?.getAttribute('role')).toBe('list');
  });

  it('marks each status with its own tag and icon, never colour alone', () => {
    fixture.componentRef.setInput('steps', [
      ...STEPS,
      { key: 'migrate-2', label: 'Migrate', status: 'failed', statusLabel: 'Failed' },
    ]);

    const tags = items().map((item) => item.querySelector('app-status-tag') as HTMLElement);
    expect(tags.map((tag) => tag.className)).toEqual([
      'status-tag status-tag--success',
      'status-tag status-tag--info',
      'status-tag status-tag--neutral',
      'status-tag status-tag--neutral',
      'status-tag status-tag--danger',
    ]);
    const glyphs = tags.map((tag) => {
      const classes = Array.from(tag.querySelector('i')?.classList ?? []);
      return classes.filter((name) => name !== 'fa-solid');
    });
    expect(glyphs).toEqual([['fa-circle-check'], ['fa-spinner'], ['fa-clock'], ['fa-circle-minus'], ['fa-circle-xmark']]);
    expect(tags.every((tag) => tag.querySelector('i')?.getAttribute('aria-hidden') === 'true')).toBe(true);
  });

  it('is an empty list while the job names no step yet', () => {
    fixture.componentRef.setInput('steps', []);

    expect(items()).toEqual([]);
  });
});
