import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed, type ComponentFixture } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { MessageService } from 'primeng/api';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { errorInterceptor } from '@core/http/error.interceptor';
import { LocaleStore } from '@core/i18n/locale.store';
import { Toaster } from '@shared/toaster/toaster';
import ar from '../../i18n/ar.json';
import en from '../../i18n/en.json';
import { FilesStore } from '../../state/files.store';
import { FOLDER, ROOT, SERVER_ID } from '../../testing/files.fixtures';
import { NewFolderDialog } from './new-folder';

describe('NewFolderDialog', () => {
  let http: HttpTestingController;
  let close: ReturnType<typeof vi.fn>;
  let fixture: ComponentFixture<NewFolderDialog>;
  let dialog: NewFolderDialog;

  const folders = `/api/files/${SERVER_ID}/folders/`;

  const rendered = (): HTMLElement => {
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  };

  const fieldError = (): string | undefined => rendered().querySelector('.field__error')?.textContent?.trim();

  beforeEach(() => {
    close = vi.fn();
    localStorage.setItem('locale', 'en');
    TestBed.configureTestingModule({
      providers: [
        FilesStore,
        MessageService,
        provideHttpClient(withInterceptors([errorInterceptor])),
        provideHttpClientTesting(),
        provideRouter([]),
        { provide: MatDialogRef, useValue: { close } },
        { provide: MAT_DIALOG_DATA, useValue: { data: { folder: ROOT } } },
      ],
    });
    TestBed.inject(LocaleStore).register({ en, ar });
    TestBed.inject(FilesStore).server.set(SERVER_ID);
    vi.spyOn(TestBed.inject(Toaster), 'add').mockReturnValue(undefined);
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(NewFolderDialog);
    dialog = fixture.componentInstance;
  });

  afterEach(() => {
    http.verify();
    TestBed.resetTestingModule();
    localStorage.clear();
    vi.restoreAllMocks();
  });

  it('says where the folder goes, the path read left to right', () => {
    expect(rendered().querySelector('p')?.textContent?.trim()).toBe(`It is created in ⁦${ROOT}⁩.`);
  });

  it('holds the create until the name can be used, and says why under the field', async () => {
    expect(fieldError()).toBeUndefined();

    await dialog.submit();
    expect(fieldError()).toBe('Enter a name for the folder.');

    dialog.onName('a/b');
    expect(fieldError()).toBe('Use a name with no / or \\ in it.');

    dialog.onName('..');
    expect(fieldError()).toBe('A folder cannot be named "." or "..".');
    await dialog.submit();

    http.expectNone(folders);
    expect(close).not.toHaveBeenCalled();
  });

  it('creates the folder in the folder it was opened on, then closes with it', async () => {
    dialog.onName('  photos ');

    const creating = dialog.submit();
    const request = http.expectOne(folders);
    expect(request.request.body).toEqual({ path: ROOT, name: 'photos' });
    request.flush(FOLDER, { status: 201, statusText: 'Created' });
    await creating;

    expect(close).toHaveBeenCalledWith(FOLDER);
  });

  it('says under the field when the name is taken, and clears it as the reader types', async () => {
    dialog.onName('photos');

    const creating = dialog.submit();
    http
      .expectOne(folders)
      .flush({ error: { code: 'file_exists', message: 'Server prose' } }, { status: 409, statusText: 'Conflict' });
    await creating;

    expect(close).not.toHaveBeenCalled();
    expect(fieldError()).toBe('A file or folder with this name already exists here.');
    expect(rendered().querySelector('p-message')).toBeNull();

    dialog.onName('photos-2');
    expect(fieldError()).toBeUndefined();
  });

  it('says any other failure above the field', async () => {
    dialog.onName('photos');

    const creating = dialog.submit();
    http
      .expectOne(folders)
      .flush(
        { error: { code: 'remote_permission_denied', message: 'Server prose' } },
        { status: 403, statusText: 'Forbidden' },
      );
    await creating;

    expect(rendered().querySelector('p-message')?.textContent).toContain(
      'Access to the folder or file was denied on the server.',
    );
    expect(fieldError()).toBeUndefined();
  });
});
