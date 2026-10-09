import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { Breadcrumb } from './breadcrumb';

describe('Breadcrumb', () => {
  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideRouter([])] });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
  });

  it('links every step but the last, which is the current page', () => {
    const fixture = TestBed.createComponent(Breadcrumb);
    fixture.componentRef.setInput('label', 'Location');
    fixture.componentRef.setInput('items', [
      { label: '/srv/app', link: [], queryParams: { path: '/srv/app' }, icon: 'fa-solid fa-folder' },
      { label: 'uploads', link: [], queryParams: { path: '/srv/app/uploads' } },
    ]);
    fixture.detectChanges();
    const html = fixture.nativeElement as HTMLElement;

    expect(html.querySelector('nav')?.getAttribute('aria-label')).toBe('Location');
    const links = html.querySelectorAll('a');
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute('href')).toBe('/?path=%2Fsrv%2Fapp');
    expect(html.querySelector('[aria-current="page"]')?.textContent?.trim()).toBe('uploads');
  });
});
