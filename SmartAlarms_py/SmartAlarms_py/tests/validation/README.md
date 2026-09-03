# Validation tests

This folder contains the benchmark validation assets and the tests that exercise them.

## Contents

- `golden_reference.*`: expected benchmark outputs
- `sample_service_response.*`: sample service response used as benchmark input for the validation tests
- `iteration_template.*`: per-run output template with ROUGE, estimated cost, latency, Top-K, and related-incident correlation/precision

## Run

From the project root:

```bash
pytest tests/validation
```

To generate a validation report from the offline CLI:

```bash
python -m tests.validation.cli \
  --references tests/validation/golden_reference.json \
  --outputs tests/validation/sample_service_response.json \
  --output /tmp/validation_report.json
```

If you need the ROUGE dependency locally, install the project requirements first:

```bash
pip install -r requirements.txt
```
