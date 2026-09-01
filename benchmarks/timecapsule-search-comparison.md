# TimeCapsule search comparison

## Question

Does coverage guidance find more useful future behavior than a matched random
search, under the same unique-candidate evaluation budget?

## Method

- 200 paired trials, seeds `0..199`.
- 128 unique future-input fingerprints evaluated per strategy per trial.
- Both arms use the same seeded proposal process: eight fresh scenarios and
  four mutations per round, with the same mutation operators and candidate
  pool size.
- The random baseline chooses a corpus parent uniformly from the evaluated
  batch. The coverage-guided arm chooses the candidate with the most unseen
  coverage features, then uses total feature count and fingerprint as stable
  tie-breakers.
- A behavior is the sorted set of observable coverage features (event kinds,
  adjacent event pairs, timing windows, delay buckets, wake count, and outcome
  signature).
- The rare target is the exact `active_dispute_contact` failure signature.
  Combined failures are not counted as the rare target.
- Quantiles use the nearest observed values; the median is the standard sample
  median. “First rare failure” quantiles are conditional on trials that found
  the rare target; not-found counts are reported separately.

Run it from the example directory:

```bash
cd examples/timecapsule-py
python3 main.py benchmark --trials 200 --budget 128 --seed 0 \
  --output runs/search-benchmark.json
```

## Result

Measured on 2026-09-01 on an Apple Silicon machine. The raw per-trial JSON is
written to the ignored `runs/` directory by the command above.

| Strategy | Unique behaviors p25 / median / p75 | Failure signatures median | Rare hit rate | First rare failure p25 / median / p75 (hits) |
| --- | ---: | ---: | ---: | ---: |
| Random mutation | 92 / 95 / 98 | 4 | 86.5% (173/200) | 12 / 29 / 53 |
| Coverage-guided | 97 / 99 / 103 | 4 | 91.0% (182/200) | 12 / 30.5 / 61 |

Every trial evaluated exactly 128 unique candidates. Across paired trials,
coverage guidance produced more unique behaviors in 151 trials, tied in 7,
and lost in 42. Among the 162 pairs where both arms found the rare failure,
coverage guidance found it first in 55, random search in 58, with 49 ties.

## Conclusion

Coverage guidance has a measurable breadth benefit: the median trial exposed
four more unique behavior signatures, and the rare-target hit rate increased
by 4.5 percentage points. It does **not** demonstrate reliable faster rare
failure discovery: the conditional median was slightly slower and random won
the paired first-hit comparison by a small margin.

The defensible product claim is therefore: coverage guidance is useful for
exploring a broader behavioral surface under a fixed budget. It is not yet
evidence that coverage-guided search universally beats random search at finding
rare failures. The strategy should remain available as a breadth-oriented
search mode, not be presented as a proven superiority result.
