import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it } from 'vitest';

import { LocaleStore } from '@core/i18n/locale.store';
import type { Job } from '@core/jobs/job.types';
import { moveDetailOf } from '../../data/move-detail';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { BLOCKED, PLANNED } from '../../testing/relocation.fixtures';
import { MovePlan } from './move-plan';

describe('MovePlan', () => {
  const render = async (job: Job, locale = 'en'): Promise<HTMLElement> => {
    localStorage.setItem('locale', locale);
    TestBed.configureTestingModule({});
    TestBed.inject(LocaleStore).register({ en, ar });
    const fixture = TestBed.createComponent(MovePlan);
    fixture.componentRef.setInput('detail', moveDetailOf(job.detail));
    await fixture.whenStable();
    return fixture.nativeElement as HTMLElement;
  };

  const sections = (root: HTMLElement): Map<string, string> =>
    new Map(
      Array.from(root.querySelectorAll('section[aria-label]'), (section) => [
        section.getAttribute('aria-label') ?? '',
        section.textContent?.replace(/\s+/g, ' ').trim() ?? '',
      ]),
    );

  afterEach(() => {
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('says what the new server runs, what it installs and the notes for the whole move', async () => {
    const root = await render(PLANNED);
    const text = root.textContent?.replace(/\s+/g, ' ') ?? '';

    expect(text).toContain('New server: ubuntu 24.04 on amd64');
    expect(text).toContain('docker-ce docker-compose-plugin python3-venv');
    expect(text).toContain('Both servers are the same machine.');
    expect(root.querySelectorAll('app-notice[severity="danger"]')).toHaveLength(0);
  });

  it('lists what each application carries, and why its database volume stays', async () => {
    const shop = sections(await render(PLANNED)).get('Shop') ?? '';

    expect(shop).toContain('/srv/shop');
    expect(shop).toContain('52.4 MB');
    expect(shop).toContain('Left out: db.sqlite3');
    expect(shop).toContain('main 0123456789ab');
    expect(shop).toContain('shop-web:latest 314.6 MB');
    expect(shop).toContain('postgres:16 already there');
    expect(shop).toContain("shop_pgdata the database's own data, restored instead");
    expect(shop).toContain('postgresql: a new database, then the fresh backup restored');
    expect(shop).toContain('A compose file names the old folder.');
  });

  it('shows a host application with its services, its rebuilt Python and its shared database', async () => {
    const blog = sections(await render(PLANNED)).get('Blog') ?? '';

    expect(blog).toContain('/home/ops/blog');
    expect(blog).toContain('size unknown');
    expect(blog).toContain('mysql on another machine: shared, never restored over');
    expect(blog).toContain('The virtualenv is made again and its packages installed (Python 3.11)');
    expect(blog).toContain('blog.service');
    expect(blog).toContain('nginx: blog.conf');
    expect(blog).toContain('Python 3.11 here and 3.12 on the new server');
  });

  it('puts every blocker first, naming the application it belongs to', async () => {
    const root = await render(BLOCKED);

    const blockers = Array.from(root.querySelectorAll('app-notice[severity="danger"]'), (notice) =>
      notice.textContent?.replace(/\s+/g, ' ').trim(),
    );
    expect(blockers).toEqual([
      'Shop: /srv/shop already holds something on the new server.',
      'The new server has no sudo, so nothing can be installed.',
    ]);
  });

  it('reads in Arabic with the same facts', async () => {
    const root = await render(PLANNED, 'ar');
    const text = root.textContent ?? '';

    expect(text).toContain('docker-ce');
    expect(text).not.toContain('relocation.');
  });
});
