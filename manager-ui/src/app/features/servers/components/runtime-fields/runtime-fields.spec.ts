import { TestbedHarnessEnvironment } from '@angular/cdk/testing/testbed';
import { TestBed } from '@angular/core/testing';
import { MatRadioGroupHarness } from '@angular/material/radio/testing';
import { MatInputHarness } from '@angular/material/input/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import type { Runtime } from '../../data/servers.types';
import { RuntimeFields } from './runtime-fields';
import type { RuntimeSettings } from './runtime-fields.types';

describe('RuntimeFields', () => {
  const render = async (runtime: Runtime) => {
    TestBed.configureTestingModule({});
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(RuntimeFields);
    fixture.componentRef.setInput('runtime', runtime);
    fixture.componentRef.setInput('composeService', '');
    fixture.componentRef.setInput('composeFiles', ['compose.yaml']);
    const changes: Partial<RuntimeSettings>[] = [];
    fixture.componentInstance.changed.subscribe((change) => changes.push(change));
    await fixture.whenStable();
    return { fixture, changes, loader: TestbedHarnessEnvironment.loader(fixture) };
  };

  afterEach(() => TestBed.resetTestingModule());

  it('offers the two places a project runs and asks nothing more for the host', async () => {
    const { loader, changes } = await render('host');

    const group = await loader.getHarness(MatRadioGroupHarness);
    const labels = await Promise.all((await group.getRadioButtons()).map((button) => button.getLabelText()));
    expect(labels).toEqual(['On the server', 'In a Docker Compose service']);
    expect(await loader.getAllHarnesses(MatInputHarness)).toHaveLength(0);

    await (await group.getRadioButtons({ label: 'In a Docker Compose service' }))[0].check();
    expect(changes).toEqual([{ runtime: 'compose' }]);
  });

  it('asks for the service under Docker Compose and passes on what is typed and removed', async () => {
    const { fixture, loader, changes } = await render('compose');

    const service = await loader.getHarness(MatInputHarness.with({ selector: '[name="compose_service"]' }));
    await service.setValue('backend');
    fixture.componentInstance.removeFile(0);

    expect(changes.at(-2)).toEqual({ compose_service: 'backend' });
    expect(changes.at(-1)).toEqual({ compose_files: [] });
  });
});
