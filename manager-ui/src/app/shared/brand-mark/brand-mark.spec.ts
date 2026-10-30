import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { BrandMark } from './brand-mark';

describe('BrandMark', () => {
  let fixture: ComponentFixture<BrandMark>;

  const image = (): HTMLImageElement => {
    fixture.detectChanges();
    return (fixture.nativeElement as HTMLElement).querySelector('img') as HTMLImageElement;
  };

  beforeEach(() => {
    localStorage.setItem('locale', 'en');
    fixture = TestBed.createComponent(BrandMark);
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('shows the logo from the bundle, named DBS, at the small size by default', () => {
    expect(image().getAttribute('src')).toBe('logo.svg');
    expect(image().alt).toBe('DBS');
    expect((fixture.nativeElement as HTMLElement).classList).not.toContain('brand-mark--large');
  });

  it('stays out of the accessibility tree when a heading already names the page', () => {
    fixture.componentRef.setInput('decorative', true);

    expect(image().alt).toBe('');
  });

  it('takes the large size where it heads a card', () => {
    fixture.componentRef.setInput('size', 'large');
    fixture.detectChanges();

    expect((fixture.nativeElement as HTMLElement).classList).toContain('brand-mark--large');
  });
});
