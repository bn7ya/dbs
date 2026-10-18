import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Notice } from '@shared/notice/notice';
import type { ContainerEngine, EngineReport, ServerCheckReport } from '../../data/servers.types';
import type { EngineLook, EngineState, EngineView } from './engines-report.types';

const ENGINES: readonly ContainerEngine[] = ['docker', 'podman'];

const PERMISSION_DENIED = 'engine_permission_denied';

const LOOKS: Readonly<Record<EngineState, EngineLook>> = {
  absent: { icon: 'fa-solid fa-circle-minus', muted: true },
  denied: { icon: 'fa-solid fa-lock', muted: false },
  broken: { icon: 'fa-solid fa-circle-xmark', muted: false },
  ready: { icon: 'fa-solid fa-circle-check', muted: false },
};

@Component({
  selector: 'app-engines-report',
  imports: [Notice, TranslatePipe],
  templateUrl: './engines-report.html',
  styleUrl: './engines-report.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class EnginesReport {
  readonly report = input.required<ServerCheckReport>();

  protected readonly system = computed(() => this.report().system ?? null);

  protected readonly engines = computed<readonly EngineView[]>(() =>
    ENGINES.map((engine) => viewOf(engine, this.report().engines?.[engine])),
  );

  protected readonly denied = computed(() => this.engines().some((engine) => engine.state === 'denied'));

  protected readonly timeout = computed(() => this.report().timeout ?? null);

  look(state: EngineState): EngineLook {
    return LOOKS[state];
  }
}

function viewOf(engine: ContainerEngine, report: EngineReport | undefined): EngineView {
  if (!report?.installed) {
    return { engine, state: 'absent', version: null, compose: null, said: '' };
  }
  if (!report.usable) {
    const denied = report.error === PERMISSION_DENIED;
    return { engine, state: denied ? 'denied' : 'broken', version: null, compose: null, said: denied ? '' : report.error };
  }
  return { engine, state: 'ready', version: report.version, compose: report.compose, said: '' };
}
