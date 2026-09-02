"""Regenerate the synthetic corpus behind the DBS anomaly base model."""

import argparse
import os
import sys
from datetime import date

import django
from django.conf import settings

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not settings.configured:
    settings.configure(SECRET_KEY="dbs-training", USE_TZ=True, INSTALLED_APPS=[])
    django.setup()

from dbs.security import baseline, synthetic  # noqa: E402


def report(forest, rows, attacks):
    normal = forest.score_samples(rows)
    print(f"normal rows: {len(rows)}")
    print(f"  score mean {normal.mean():.4f}  min {normal.min():.4f}")
    threshold = sorted(normal)[int(len(normal) * 0.02)]
    print(f"  2nd percentile (working threshold) {threshold:.4f}")
    for name, vectors in sorted(attacks.items()):
        scores = forest.score_samples(vectors)
        caught = sum(1 for score in scores if score < threshold)
        print(
            f"{name:>18}: mean {scores.mean():.4f}  "
            f"caught {caught}/{len(vectors)}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=4000)
    parser.add_argument("--seed", type=int, default=20260302)
    parser.add_argument("--report", action="store_true")
    options = parser.parse_args()

    rows = synthetic.normal_rows(options.rows, options.seed)
    path = baseline.write_corpus(rows, options.seed, date.today().isoformat())
    print(f"wrote {path} ({path.stat().st_size:,} bytes, {len(rows)} rows)")

    if options.report:
        baseline.reset()
        report(baseline.base_model(), rows, synthetic.attack_rows())


if __name__ == "__main__":
    main()
