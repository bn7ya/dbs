import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { Notice } from '@shared/notice/notice';
import { isolated } from '@shared/isolated/isolated';
import type { Application, Compatibility } from '../../data/applications.types';
import { NextSteps } from '../next-steps/next-steps';
import type { Presence, PresenceLook, ReportRow, RootRow, Verdict } from './check-report.types';

const PRESENCE_LOOKS: Readonly<Record<Presence, PresenceLook>> = {
  found: { icon: 'fa-solid fa-circle-check', muted: false },
  missing: { icon: 'fa-solid fa-circle-xmark', muted: false },
  notSet: { icon: 'fa-solid fa-circle-minus', muted: true },
  notChecked: { icon: 'fa-solid fa-circle-question', muted: true },
  running: { icon: 'fa-solid fa-circle-check', muted: false },
  stopped: { icon: 'fa-solid fa-circle-xmark', muted: false },
};

@Component({
  selector: 'app-check-report',
  imports: [NextSteps, Notice, TranslatePipe],
  templateUrl: './check-report.html',
  styleUrl: './check-report.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CheckReport {
  readonly application = input.required<Application>();
  readonly versions = input<Compatibility | null>(null);

  protected readonly report = computed(() => this.application().last_check_report);

  protected readonly rows = computed<readonly ReportRow[]>(() => {
    const application = this.application();
    const report = this.report();
    const versions = this.versions();
    const container = report.container;
    return [
      valueRow('applications.check.report.system', report.system, 'notChecked'),
      ...(versions ? [valueRow('applications.check.report.localVersion', versions.local_version, 'missing')] : []),
      valueRow('applications.check.report.dbsVersion', report.dbs_version, 'missing'),
      ...(container
        ? [
            valueRow(`applications.check.report.engine.${container.engine}`, container.version, 'missing'),
            {
              labelKey: 'applications.check.report.container',
              value: null,
              presence: container.running ? 'running' : 'stopped',
            } satisfies ReportRow,
          ]
        : []),
      presenceRow('applications.check.report.backupCommand', report.backup_command),
      application.env_path
        ? presenceRow('applications.check.report.envFile', report.env_file)
        : { labelKey: 'applications.check.report.envFile', value: null, presence: 'notSet' },
      presenceRow('applications.check.report.remoteBackupDir', report.remote_backup_dir),
      ...(application.kind !== 'host'
        ? [presenceRow('applications.check.report.timeout', application.timeout_in_container)]
        : []),
    ];
  });

  protected readonly roots = computed<readonly RootRow[]>(() =>
    this.application().file_roots.map((path) => ({ path, presence: presenceOf(this.report().roots?.[path]) })),
  );

  protected readonly engineSaid = computed(() => this.report().container?.error ?? '');

  protected readonly verdict = computed<Verdict>(() => {
    const versions = this.versions();
    if (versions) {
      if (!versions.installed) {
        return 'notInstalled';
      }
      return versions.compatible ? 'ready' : 'incompatible';
    }
    return this.report().dbs_version ? 'unknown' : 'notInstalled';
  });

  protected readonly dbsError = computed(() => this.report().dbs_error ?? '');

  protected readonly python = computed(() => isolated(this.application().python_path));

  protected readonly suggestion = computed(() => {
    const found = this.report().python_suggestion;
    return found ? { version: found.dbs_version, python: isolated(found.python_path) } : null;
  });

  protected readonly panelSchedules = computed(() => this.report().panel_schedule?.enabled === true);

  protected readonly problems = computed(() => this.report().problems ?? []);

  look(presence: Presence): PresenceLook {
    return PRESENCE_LOOKS[presence];
  }
}

function presenceOf(value: boolean | null | undefined): Presence {
  if (value === true) {
    return 'found';
  }
  return value === false ? 'missing' : 'notChecked';
}

function presenceRow(labelKey: string, value: boolean | null | undefined): ReportRow {
  return { labelKey, value: null, presence: presenceOf(value) };
}

function valueRow(labelKey: string, value: string | null | undefined, absent: Presence): ReportRow {
  return value ? { labelKey, value, presence: 'found' } : { labelKey, value: null, presence: absent };
}
