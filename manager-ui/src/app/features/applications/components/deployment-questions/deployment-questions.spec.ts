import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import type { DeploymentProfile } from '../../data/applications.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { DeploymentQuestions } from './deployment-questions';

describe('DeploymentQuestions', () => {
  const render = async (profile: DeploymentProfile, detected: DeploymentProfile | null = null) => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({});
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(DeploymentQuestions);
    const changes: DeploymentProfile[] = [];
    fixture.componentRef.setInput('profile', profile);
    fixture.componentRef.setInput('detected', detected);
    fixture.componentInstance.changed.subscribe((value) => changes.push(value));
    await fixture.whenStable();
    return { fixture, changes, loader: TestbedHarnessEnvironment.loader(fixture) };
  };

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('starts every question on Not sure and asks the host questions while it is open', async () => {
    const { fixture, loader } = await render({});

    const groups = await loader.getAllHarnesses(MatRadioGroupHarness);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(groups.length).toBe(8);
    expect(await groups[0].getCheckedValue()).toBe('');
    expect(text).toContain('Where does Django run?');
    expect(text).toContain('Which web server is in front of it?');
  });

  it('says what an answer becomes when one is picked', async () => {
    const { loader, changes } = await render({});

    const [runsIn] = await loader.getAllHarnesses(MatRadioGroupHarness);
    await runsIn.checkRadioButton({ label: 'In a Docker or Podman Compose service' });

    expect(changes.at(-1)).toEqual({ runs_in: 'compose' });
  });

  it('leaves out the host questions for a Compose project and shows what was found', async () => {
    const { fixture, loader } = await render({ runs_in: 'compose' }, { runs_in: 'compose', database: 'mysql' });

    const groups = await loader.getAllHarnesses(MatRadioGroupHarness);
    const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
    expect(groups.length).toBe(6);
    expect(text).toContain('Found: MySQL');
    expect(text).not.toContain('What keeps it running?');
  });
});
