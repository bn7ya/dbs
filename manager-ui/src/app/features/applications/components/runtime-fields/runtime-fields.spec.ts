import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatInputHarness } from '@angular/material/input/testing';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import type { ApplicationEngine, ApplicationKind } from '../../data/applications.types';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { RuntimeFields } from './runtime-fields';
import type { RuntimeErrors, RuntimeSettings } from './runtime-fields.types';

describe('RuntimeFields', () => {
  const render = async (kind: ApplicationKind, engine: ApplicationEngine = '', errors: RuntimeErrors = {}) => {
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({});
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(RuntimeFields);
    fixture.componentRef.setInput('kind', kind);
    fixture.componentRef.setInput('engine', engine);
    fixture.componentRef.setInput('composeProject', '');
    fixture.componentRef.setInput('composeService', '');
    fixture.componentRef.setInput('composeFiles', ['compose.yaml']);
    fixture.componentRef.setInput('containerName', '');
    fixture.componentRef.setInput('errors', errors);
    const changes: Partial<RuntimeSettings>[] = [];
    fixture.componentInstance.changed.subscribe((change) => changes.push(change));
    await fixture.whenStable();
    return { fixture, changes, loader: TestbedHarnessEnvironment.loader(fixture) };
  };

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('offers the three places an application runs and asks nothing more for the host', async () => {
    const { loader, changes } = await render('host');

    const groups = await loader.getAllHarnesses(MatRadioGroupHarness);
    expect(groups).toHaveLength(1);
    const labels = await Promise.all((await groups[0].getRadioButtons()).map((button) => button.getLabelText()));
    expect(labels).toEqual(['On the server', 'In a Compose service', 'In a container']);
    expect(await loader.getAllHarnesses(MatInputHarness)).toHaveLength(0);

    await (await groups[0].getRadioButtons({ label: 'In a container' }))[0].check();
    expect(changes).toEqual([{ kind: 'container' }]);
  });

  it('asks for the engine and the service under Compose, and passes on what is typed and removed', async () => {
    const { fixture, loader, changes } = await render('compose', 'docker');

    const groups = await loader.getAllHarnesses(MatRadioGroupHarness);
    expect(await groups[1].getCheckedValue()).toBe('docker');
    await (await groups[1].getRadioButtons({ label: 'Podman' }))[0].check();
    const service = await loader.getHarness(MatInputHarness.with({ selector: '[name="compose_service"]' }));
    await service.setValue('backend');
    fixture.componentInstance.removeFile(0);

    expect(changes[0]).toEqual({ engine: 'podman' });
    expect(changes.at(-2)).toEqual({ compose_service: 'backend' });
    expect(changes.at(-1)).toEqual({ compose_files: [] });
  });

  it('asks for the container name in a container, and says when the engine is missing', async () => {
    const { fixture, loader } = await render('container', '', { engine: 'engine_required' });

    expect(await loader.getHarness(MatInputHarness.with({ selector: '[name="container_name"]' }))).toBeTruthy();
    expect((fixture.nativeElement as HTMLElement).textContent).toContain('Choose Docker or Podman.');
  });

  it('clears the engine when the application moves back onto the host', async () => {
    const { loader, changes } = await render('compose', 'docker');

    const group = (await loader.getAllHarnesses(MatRadioGroupHarness))[0];
    await (await group.getRadioButtons({ label: 'On the server' }))[0].check();

    expect(changes).toEqual([{ kind: 'host', engine: '' }]);
  });
});
