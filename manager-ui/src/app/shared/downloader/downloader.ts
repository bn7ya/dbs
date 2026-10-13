import { DOCUMENT } from '@angular/common';
import { Injectable, inject } from '@angular/core';

// A link the browser follows itself streams a large file to disk instead of holding it in memory.
@Injectable({ providedIn: 'root' })
export class Downloader {
  private readonly document = inject(DOCUMENT);

  start(url: string): void {
    const link = this.document.createElement('a');
    link.href = url;
    link.download = '';
    link.click();
  }
}
