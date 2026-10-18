import { Component, inject } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, provideRouter, Router, RouterOutlet } from '@angular/router';
import { afterEach, describe, expect, it } from 'vitest';

import { routeParam } from './route-param';

@Component({ selector: 'app-probe', template: '' })
class Probe {
  readonly applicationId = routeParam(inject(ActivatedRoute), 'applicationId');
  readonly missing = routeParam(inject(ActivatedRoute), 'serverId');
}

@Component({ selector: 'app-host', imports: [RouterOutlet], template: '<router-outlet />' })
class Host {}

describe('routeParam', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('reads a parameter from the route that holds it and follows changes', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          {
            path: 'applications/:applicationId',
            children: [{ path: 'backups', component: Probe }],
          },
        ]),
      ],
    });
    const fixture = TestBed.createComponent(Host);
    const router = TestBed.inject(Router);

    await router.navigateByUrl('/applications/a1/backups');
    fixture.detectChanges();
    const probe = fixture.debugElement.children[1].componentInstance as Probe;

    expect(probe.applicationId()).toBe('a1');
    expect(probe.missing()).toBeNull();

    await router.navigateByUrl('/applications/a2/backups');
    expect(probe.applicationId()).toBe('a2');
  });
});
