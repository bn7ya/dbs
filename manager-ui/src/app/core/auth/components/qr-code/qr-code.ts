import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import qrcode from 'qrcode-generator';

const CELL_SIZE = 6;
const QUIET_ZONE = 4 * CELL_SIZE;

@Component({
  selector: 'app-qr-code',
  templateUrl: './qr-code.html',
  styleUrl: './qr-code.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class QrCode {
  readonly value = input.required<string>();
  readonly label = input.required<string>();

  protected readonly image = computed(() => {
    const code = qrcode(0, 'M');
    code.addData(this.value());
    code.make();
    return code.createDataURL(CELL_SIZE, QUIET_ZONE);
  });
}
