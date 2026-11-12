# Task 1 report

Implemented `QuantitySource` and `ProvenancedQuantity`, conservative conversion from existing `SourceRef`/dict/null, trusted-only native API and environment mapping, mock retention under damaged metadata, aware timestamps, stable deduplication and conflict rejection, coverage degradation, exact decimal strings, and legacy source mode projection. Model validation checks source-derived origins, environments, and input references. No source systems were accessed; `SourceRef` was not modified.

Files: `src/manufacturing_platform/workflow/quantity_provenance.py`, `tests/workflow/test_quantity_provenance.py`.

RED: `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest tests/workflow/test_quantity_provenance.py -q --tb=short` failed at collection with `ModuleNotFoundError: No module named 'manufacturing_platform.workflow.quantity_provenance'` (expected missing feature). Additional regression RED: same command yielded 1 failed, 7 passed because legacy version string was lost.

GREEN: same command yielded `8 passed in 0.01s`; `git diff --check` passed. Tests cover mixed and damaged mock inputs, trusted API, unknown metadata/environment, null, precision, earliest and missing times, duplicates/conflicts, coverage ordering, JSON round trip and forged projections.

Self-review: no IO, writes, source calls, or changes to existing contracts. `trusted` is an internal caller argument and must only be provided after persistent binding verification; the pure function cannot perform that verification. Integration and full suite are outside this isolated task and remain for the parent.

## Review fixes

RED command: `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest tests/workflow/test_quantity_provenance.py -q --tb=short`

```text
...F....FFFFFFFFF....FF                                                  [100%]
FAILED test_missing_sources_and_time_do_not_fabricate_values: expected ['unknown'], got []
FAILED test_quantity_values_reject_non_plain_decimals[NaN]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[Infinity]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[-Infinity]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[1e999]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[garbage]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[ 1]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[1.]: DID NOT RAISE ValidationError
FAILED test_quantity_values_reject_non_plain_decimals[.1]: DID NOT RAISE ValidationError
FAILED test_direct_and_json_projection_reject_forged_merge_fields: DID NOT RAISE ValidationError
FAILED test_empty_projection_requires_unknown_identity_and_role: DID NOT RAISE ValidationError
12 failed, 11 passed in 0.05s
```

The tests for `1.` and `.1` were corrected to accept these plain decimal forms; all other RED failures expose missing contract enforcement.

GREEN command: `PYTHONPATH=src /private/tmp/manufacturing-contract-py311/bin/python -m pytest tests/workflow/test_quantity_provenance.py -q --tb=short`

```text
........................                                                 [100%]
24 passed in 0.02s
```

`git diff --check` passed. Decimal strings retain their original representation without float conversion; shared merge logic enforces source identity, timestamps, coverage and empty-source behavior on helper and model/JSON paths. No production access occurred.

## Identity length bounds review fix

RED command: `PYTHONPATH=src pytest -q tests/workflow/test_quantity_provenance.py -k oversized`

```text
9 failed, 1 passed, 24 deselected in 0.05s
```

The nine failures showed that 201-character `system`, `object_type`, and `external_id` values still received `manual`, `file`, or trusted `api` provenance. The oversized mock identity case passed, preserving recognizable mock mode. An initial run without `PYTHONPATH=src` failed during conftest import (`ModuleNotFoundError`); the RED run above is the corrected test invocation.

GREEN command: `PYTHONPATH=src pytest -q tests/workflow/test_quantity_provenance.py`

```text
34 passed in 0.02s
```

`git diff --check` passed. Identity eligibility now requires each field to be a nonblank string of length 1 through 200, while retaining the strict positive integer version check and the explicit mock mode exception. No production/source calls were made.

Code and test commit: `dec886621a00f40b61c6ceeff855d611bec19f34` (`Fix quantity provenance identity bounds`).
