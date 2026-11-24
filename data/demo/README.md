Files for `python -m pipeline demo`. All invented.

- `review_decisions.json`: scripted approve / reject decisions for run 1, so the demo can run without a person. In real use a person decides with `python -m pipeline review`.
- `results.json`: made-up results for run 1 variants, keyed by variant id. One row in each file belongs to a rejected variant, to show that results are only imported for approved variants.
