import { describe, expect, it } from 'vitest';

import { DEPLOYED, DEPLOY_STOPPED, MOVED_FROM_CHOSEN, REHEARSED_WITHOUT_SOURCE, TARGET } from '../testing/redeploy.fixtures';
import { deployOutcomeOf, failedStepOf, isRehearsal, jobStepsOf, moveOutcomeOf } from './job-detail';

describe('the detail of a redeploy job', () => {
  it('lists the steps it names, each deploy step with its place in the list', () => {
    expect(jobStepsOf(DEPLOY_STOPPED.detail)).toEqual([
      { step: 'check', status: 'succeeded' },
      { step: 'git_pull', index: 0, status: 'succeeded' },
      { step: 'compose_build', index: 1, status: 'failed' },
      { step: 'final_check', status: 'skipped' },
    ]);
  });

  it('leaves out anything that is not a step, and reads no steps as none', () => {
    expect(
      jobStepsOf({
        steps: [{ step: 'check', status: 'succeeded' }, 'check', { step: 'restore' }, { step: 'env', status: 'lost' }, null],
      }),
    ).toEqual([{ step: 'check', status: 'succeeded' }]);
    expect(jobStepsOf({})).toEqual([]);
    expect(jobStepsOf({ steps: 'check' })).toEqual([]);
  });

  it('names the step it stopped at and whether it was a rehearsal', () => {
    expect(failedStepOf(DEPLOY_STOPPED.detail)).toBe('compose_build');
    expect(failedStepOf(DEPLOYED.detail)).toBeNull();
    expect(isRehearsal(DEPLOY_STOPPED.detail)).toBe(false);
    expect(isRehearsal(REHEARSED_WITHOUT_SOURCE.detail)).toBe(true);
    expect(isRehearsal({})).toBe(false);
  });

  it('reads a deploy that can be reverted, and the code and image before and after it', () => {
    expect(deployOutcomeOf(DEPLOY_STOPPED.detail)).toEqual({ revertable: true, before: {}, after: {} });
    expect(deployOutcomeOf(DEPLOYED.detail)).toEqual({
      revertable: false,
      before: { git_head: 'a1b2c3d4e5f6', image: 'sha256:0123456789abcdef' },
      after: { git_head: 'f6e5d4c3b2a1', image: 'sha256:fedcba9876543210' },
    });
    expect(deployOutcomeOf({ before: { git_head: 7, image: 'sha256:1' } }).before).toEqual({ image: 'sha256:1' });
  });

  it('reads where a move went, and whether it used the chosen backup or found the source silent', () => {
    expect(moveOutcomeOf(MOVED_FROM_CHOSEN.detail)).toEqual({
      target: TARGET,
      revertable: false,
      usedChosenBackup: true,
      sourceSilent: false,
    });
    expect(moveOutcomeOf(REHEARSED_WITHOUT_SOURCE.detail).sourceSilent).toBe(true);
    expect(moveOutcomeOf({}).target).toBeNull();
  });
});
