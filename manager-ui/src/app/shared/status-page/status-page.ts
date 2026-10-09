import { NgTemplateOutlet } from '@angular/common';
import { ChangeDetectionStrategy, Component, inject, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { MatButton } from '@angular/material/button';
import { MatCard, MatCardContent } from '@angular/material/card';

import { SHELL_FRAME } from '@core/layout/shell-frame';
import { TranslatePipe } from '@core/i18n/translate.pipe';

@Component({
  selector: 'app-status-page',
  imports: [NgTemplateOutlet, RouterLink, MatButton, MatCard, MatCardContent, TranslatePipe],
  templateUrl: './status-page.html',
  styleUrl: './status-page.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class StatusPage {
  readonly titleKey = input.required<string>();
  readonly bodyKey = input.required<string>();

  protected readonly framed = inject(SHELL_FRAME, { optional: true }) !== null;
}
