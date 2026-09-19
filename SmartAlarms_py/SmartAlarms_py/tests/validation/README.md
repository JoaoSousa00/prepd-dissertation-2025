# Validation tests

This folder contains the benchmark validation dataset, report template, and tests.

## Contents

- `golden_reference.*`: expected benchmark outputs
- `iteration_template.*`: per-run output template with semantic summary score, MRR, suggestion rank,
  service telemetry, LLM-judge telemetry, and related-incident precision

Each `reference_mitigation_suggestions` entry contains separate `investigation` and `mitigation`
fields. The LLM judge scores the summary from 1 (irrelevant) to 5 (fully equivalent). It evaluates
each reference suggestion against the generated list and records its 1-based `generated_rank`.
MRR is the reciprocal rank of the first suggestion with a score of 4 or 5, or `0.0` when none
is semantically equivalent. Related incidents use exact-ID precision.

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

Use `--repetitions` to change the number of calls made for each incident, `--max-concurrency` to
set the maximum number of simultaneous requests (default: 10), and `--service-url` if the local
service uses another address or port:

```bash
python3 -m tests.validation.cli \
  --references tests/validation/golden_reference.json \
  --service-url http://127.0.0.1:8000/incident/details \
  --repetitions 10 \
  --max-concurrency 10 \
  --output /tmp/validation_report.json
```

The report contains one case per incident. Its `results` array preserves every call in execution
order, including per-call metrics, judge decision, telemetry, and errors. Its final `average`
object contains the quality and telemetry means across successful calls; failed calls remain in
`results` but do not contribute quality metrics. Service cost and latency remain separate from
judge cost and latency.

Related incident and related page precision measure golden-reference coverage: every golden
identifier present in the response scores `1.0`, regardless of additional related items returned.
Pages use their URLs as identifiers. An empty golden reference also scores `1.0`.

Add expected page URLs to each golden reference incident with `reference_related_pages`. Either
plain URL strings or objects containing a `url` field are accepted.

The judge uses the configured GAIA credentials with `GAIA_JUDGE_MODEL` and deterministic
`temperature=0`. Configure `LLM_JUDGE_MAX_TOKENS` when the default of 2000 output tokens is not
appropriate; GAIA accepts a maximum of 128000. The CLI loads the project `.env` file before it creates the judge. Copy
`.env_template` to `.env` once and provide the real `GAIA_AUTH_ENDPOINT`, credentials, and
certificate settings there; do not put credentials in `.env_template`.

The CLI prints the incident ID before each request and its outcome afterward. It limits in-flight
service requests to `--max-concurrency`; completed calls may be printed out of request order, while
each incident's report results remain ordered by `call_number`.
