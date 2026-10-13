import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatRadioButton, MatRadioGroup } from '@angular/material/radio';

import { TranslatePipe } from '@core/i18n/translate.pipe';
import { uniqueId } from '@shared/unique-id';
import type { AssignableRole } from '../../data/accounts.types';

const ROLES: readonly AssignableRole[] = ['admin', 'operator', 'viewer'];

@Component({
  selector: 'app-role-choice',
  imports: [MatRadioGroup, MatRadioButton, TranslatePipe],
  templateUrl: './role-choice.html',
  styleUrl: './role-choice.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RoleChoice {
  readonly role = input.required<AssignableRole>();
  readonly roleChange = output<AssignableRole>();

  readonly roles = ROLES;
  readonly legendId = uniqueId('role');

  choose(role: AssignableRole | null): void {
    if (role) {
      this.roleChange.emit(role);
    }
  }
}
