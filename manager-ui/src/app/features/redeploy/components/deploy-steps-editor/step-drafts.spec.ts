import { describe, expect, it } from 'vitest';

import { BUILD, MIGRATE, PULL, UP } from '../../testing/redeploy.fixtures';
import { NO_PROBLEMS, draftOf, draftProblems, emptyDraft, hasProblems, stepOf } from './step-drafts';

describe('a deploy step being edited', () => {
  it('reads a saved step and writes it back as it was', () => {
    for (const step of [PULL, BUILD, UP, MIGRATE]) {
      expect(stepOf(draftOf(step, 1))).toEqual(step);
    }
  });

  it('starts a new step with ten minutes and nothing chosen, a requirements file named for pip', () => {
    expect(emptyDraft('git_pull', 4)).toEqual({
      key: 4,
      kind: 'git_pull',
      remote: '',
      branch: '',
      services: [],
      pull: false,
      unit: '',
      requirements: '',
      timeout: 10,
    });
    expect(stepOf(emptyDraft('git_pull', 1))).toEqual({ kind: 'git_pull', options: {}, timeout_minutes: 10 });
    expect(stepOf(emptyDraft('pip_install', 1)).options).toEqual({ requirements: 'requirements.txt' });
    expect(stepOf(emptyDraft('restart', 1)).options).toEqual({});
  });

  it('sends only the options its kind takes, trimmed', () => {
    const draft = { ...emptyDraft('git_pull', 1), remote: ' origin ', branch: ' main ', unit: 'stale.service' };

    expect(stepOf(draft).options).toEqual({ remote: 'origin', branch: 'main' });
    expect(stepOf({ ...draft, kind: 'compose_up', services: ['web'] }).options).toEqual({ services: ['web'] });
    expect(stepOf({ ...draft, kind: 'systemd_user_restart', unit: ' app.service ' }).options).toEqual({
      unit: 'app.service',
    });
  });

  it('names a problem on the field it belongs to, and none on fields its kind does not show', () => {
    const remoteAlone = { ...emptyDraft('git_pull', 1), remote: 'origin' };
    expect(draftProblems(remoteAlone)).toEqual({ ...NO_PROBLEMS, branch: 'branch_required' });

    const noUnit = { ...emptyDraft('systemd_user_restart', 1), remote: 'bad name' };
    expect(draftProblems(noUnit)).toEqual({ ...NO_PROBLEMS, unit: 'invalid_unit' });

    const badBuild = { ...emptyDraft('compose_build', 1), services: ['web server'], timeout: 0 };
    expect(draftProblems(badBuild)).toEqual({ ...NO_PROBLEMS, services: 'invalid_service', timeout: 'invalid_timeout' });
    expect(hasProblems(draftProblems(badBuild))).toBe(true);
    expect(hasProblems(draftProblems(draftOf(PULL, 1)))).toBe(false);
  });
});
