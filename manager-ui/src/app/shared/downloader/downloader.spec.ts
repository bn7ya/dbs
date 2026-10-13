import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { Downloader } from './downloader';

describe('Downloader', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    TestBed.resetTestingModule();
  });

  it('follows a link to the file, which the browser saves', () => {
    const followed: HTMLAnchorElement[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      followed.push(this);
    });

    TestBed.inject(Downloader).start('/api/backups/b1/download/?ticket=t');

    expect(followed).toHaveLength(1);
    expect(followed[0].getAttribute('href')).toBe('/api/backups/b1/download/?ticket=t');
    expect(followed[0].hasAttribute('download')).toBe(true);
    expect(followed[0].isConnected).toBe(false);
  });
});
