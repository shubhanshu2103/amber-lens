# Task: Groq as an optional vision provider

Owner: A Perception (Vrushali). Not committed yet (same working tree as T5).

## What was asked and status

| Item | Status | Evidence |
| --- | --- | --- |
| `VISION_PROVIDER=groq`, `GROQ_API_KEY` from `.env`, OpenAI-compatible endpoint, model `qwen/qwen3.8-27b` pinned and configurable; ollama kept | **done** | `providers.py`, `groq.py`, `config.py`, `.env.example` (`GROQ_MODEL`) |
| strict READ rule unchanged, local OCR confirms every value | **done** | the provider only replaces the vision call inside `read_document` |
| face check before any cloud call | **done** | `GroqVision.read` runs YuNet first and raises `FaceInPhoto` before sending; test proves no request is made |
| vision and OCR in parallel per photo | **done, with a change** | a two-worker thread pool runs both (see "Deviation") |
| 30 RPM / 8K TPM, 429 `retry-after`, `x-ratelimit-*` headers, on-disk cache | **done** | sliding one-minute window; up to 3 retries on 429; pause when remaining tokens are low; cached answers make no call |
| measure on the 10 spike photos and all 35, compare with local | **done** | "Measurements" below |

## Groq facts used (Groq public docs, read 2026-11-24)

- `qwen/qwen3.8-27b` exists and accepts images; it is listed under **Preview models**: "intended for evaluation
  purposes only and should not be used in production"; preview models "may be discontinued at short notice".
  Its predecessor `qwen/qwen3.6-27b` was shut down on 2026-09-14.
- Each image counts as 2,048 input tokens; up to 3 images and 20 MB per request; list price $0.80 / $4.00 per
  1M input / output tokens. The rate-limit table shows 30 RPM, 8K TPM, 1K RPD, 200K TPD for this model (the
  page does not label the table clearly as free tier).
- The only other Groq vision model, `meta-models/muse-spark-open`, is enterprise ("contact sales").

## Measurements (35 tuning photos, strict rule, RapidOCR + Tesseract; final after the power-unit fix)

| photos | provider | key values READ and correct | wrong READs (key) | located | s/photo total (vision, OCR in parallel) | tokens / photo | cost / photo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 (spike) | local qwen2.5vl:7b | 12 of 26 | 3 (1) | 19 of 26 | 16.6 (16.6, 7.8) | 1,580 | $0 |
| 10 (spike) | Groq qwen/qwen3.8-27b | 11 of 26 | 1 (1) | 18 of 26 | 4.9 (1.2, 4.9) | 2,202 | $0.0025 list, $0 free tier |
| 35 (all) | local qwen2.5vl:7b | 41 of 94 | 5 (2) | 67 of 94 | 15.8 (15.8, 7.2) uncached | 1,576 | $0 |
| 35 (all) | Groq qwen/qwen3.8-27b | 39 of 94 | 4 (3) | 65 of 94 | 5.3 (1.1, 5.3), max 8.3 | 2,155 | $0.0025 list, $0 free tier |

Groq's key wrong READs: hf_04 model_number (shared with local), darjja_train_14 rated_current (label blank on the
unreadable plate), hf_075 voltage (multi-row table, carries the multi_row_table warning). Its one clear misread,
darjja_train_12 power `79.0 HP` (79.0 is the compressor LRA; HP belongs to the fan motor's 1/5), is now blocked:
every power value READ needs its unit confirmed next to the number on the photo, whoever wrote the unit, and a
unit label that also touches another number is ambiguous (named test). Local counts are unchanged by the fix.

**Default (your G-2 rule):** Groq key wrong READs 3 > local 2, so the default stays `ollama`. The deployed server
uses Groq anyway (no GPU): `deploy/perception.env` sets `VISION_PROVIDER=groq`, `VISION_FALLBACK=none`.

The 6 real-model tests (4 injection variants, SRT crate label, synthetic ticket) also pass with Groq
(`6 passed in 164.55s`), so the deployed provider is held to the same injection and document checks.

## Fallback

If the provider fails (HTTP error, rate limits beyond 3 retries, a removed model), every field is DISPUTED with
the new reason `vision_unavailable` and `warnings["vision"]` names the error; nothing is guessed. With
`VISION_FALLBACK=ollama` local Ollama is tried first. A face in the photo is not a failure: the photo is refused.
Groq requests send a generic client name (`amber-lens/0.1`); Groq's edge blocks Python's default (Cloudflare 1010).
Measurement note: the first key was deleted mid-run (HTTP 401 after 7 answers); the cached answers were reused.

## Deviation

You asked for async for the API and a thread pool for OCR. Both run in a two-worker thread pool instead: it
needs no async HTTP library (none is installed; it would be a new dependency), and it also works inside the
capture server's event loop. The effect is the same: vision and OCR overlap, and the photo costs the slower.

## To measure Groq

1. Create `.env` from `.env.example` and set `GROQ_API_KEY=...` yourself (never in chat, never in git).
2. Run, with `VISION_PROVIDER=groq` in `.env`:
   `.venv/Scripts/python -m amber_lens.perception.evaluate --photos spike` then `--photos all`.
   Groq answers are cached under the model name, so the local cache is not touched.

## Tests

12 new CI tests in `test_perception_groq.py` (request shape and token count, list-price cost, face blocks the
call, cache hit makes no call, 429 retry-after, low-token pause, other HTTP errors, limiter, reset-header
parsing, provider choice and missing key). `ruff check .` clean; `pytest -q` 243 passed.

## Files added or changed

Added: `src/amber_lens/perception/groq.py`, `providers.py`, `faces.py` (face check moved out of `capture.py`),
`tests/perception/test_perception_groq.py`, this report.
Changed: `src/amber_lens/perception/reader.py` (parallel run, timings, cost from the call),
`vision.py` (tokens and cost on `VisionCall`; Ollama token counts), `config.py`, `capture.py`, `evaluate.py`
(`--photos spike`, timing and token summary, real cost), `README.md`, `.env.example`;
`tests/perception/test_perception_capture.py`, `test_perception_reader.py`, `test_perception_evaluate.py`.

## Size

groq.py 142 lines, providers.py 19, faces.py 41; reader.py 296 (parallel run in, provider choice out);
tests +130. No module over 300 lines, no function over 40. Cut: async HTTP client, retries beyond 3,
per-day budget tracking (the daily cap is reported instead).

## Proposed commit

`a: Groq vision provider with vision_unavailable fallback, power-unit rule fix (#11)`; stage the changed files
(never `.env`). The T5 and earlier Groq files were committed in `f44b349`.
