import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { LISTED } from '../testing/console.fixtures';
import { ConsoleApi } from './console.api';

describe('ConsoleApi', () => {
  let api: ConsoleApi;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    api = TestBed.inject(ConsoleApi);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
  });

  it('runs one line', async () => {
    const running = firstValueFrom(api.run({ line: 'server list' }));
    const request = http.expectOne('/api/console/');
    expect(request.request.method).toBe('POST');
    expect(request.request.body).toEqual({ line: 'server list' });
    request.flush(LISTED);

    await expect(running).resolves.toEqual(LISTED);
  });

  it('runs a line again with the password', () => {
    void firstValueFrom(api.run({ line: 'backup delete 7', password: 'hunter2' }));

    const request = http.expectOne('/api/console/');
    expect(request.request.body).toEqual({ line: 'backup delete 7', password: 'hunter2' });
    request.flush(LISTED);
  });
});
