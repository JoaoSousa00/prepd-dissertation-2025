# Validation tests

This folder contains the benchmark validation dataset, report template, and tests.

## Contents

- `golden_reference.*`: expected benchmark outputs
- `iteration_template.*`: per-run output template with ROUGE, estimated cost, latency, Top-K, and related-incident correlation/precision

Each `reference_mitigation_suggestions` entry contains separate `investigation` and
`mitigation` fields. Top-K accuracy compares only the mitigation text.

## Run

From the project root:

```bash
pytest tests/validation
```

Start the local service, then generate a validation report by requesting every incident ID in the
golden reference ten times:

```bash
uvicorn src.main:app --host 127.0.0.1 --port 8080
```

In a second terminal:

```bash
python3 -m tests.validation.cli \
  --references tests/validation/golden_reference.json \
  --output /tmp/validation_report.json
```

Use `--repetitions` to change the number of calls made for each incident and `--service-url` if the
local service uses another address or port:

```bash
python3 -m tests.validation.cli \
  --references tests/validation/golden_reference.json \
  --service-url http://127.0.0.1:8000/incident/details \
  --repetitions 10 \
  --output /tmp/validation_report.json
```

The report contains one aggregated case per incident. Each case records its total and successful
call counts, average quality and telemetry metrics, and any failed-request details.

The CLI prints the incident ID before each request and its outcome afterward. Requests are processed
sequentially, so a slow incident delays the next one.
