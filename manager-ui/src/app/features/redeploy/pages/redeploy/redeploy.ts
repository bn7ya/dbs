import { ChangeDetectionStrategy, Component, effect, inject } from '@angular/core';
import { ActivatedRoute } from '@angular/router';

import { routeParam } from '@core/routing/route-param';
import { Dialogs } from '@shared/dialogs/dialogs';
import { DeployHere } from '../../components/deploy-here/deploy-here';
import { MoveApplication } from '../../components/move-application/move-application';
import { DeployStore } from '../../state/deploy.store';
import { MoveStore } from '../../state/move.store';

@Component({
  selector: 'app-redeploy-page',
  imports: [DeployHere, MoveApplication],
  providers: [Dialogs],
  templateUrl: './redeploy.html',
  styleUrl: './redeploy.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class RedeployPage {
  private readonly deploy = inject(DeployStore);
  private readonly move = inject(MoveStore);

  readonly applicationId = routeParam(inject(ActivatedRoute), 'applicationId');

  constructor() {
    effect(() => {
      const application = this.applicationId();
      if (application !== null) {
        this.deploy.open(application);
        this.move.open(application);
      }
    });
  }
}
