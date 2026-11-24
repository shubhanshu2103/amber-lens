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
| measure on the 10 spike photos and all 35, compare with local | **local done; Groq not measured** | there is no `.env` and no `GROQ_API_KEY` on this machine |

## Groq facts used (Groq public docs, read 2026-11-24)

- `qwen/qwen3.8-27b` exists and accepts images; it is listed under **Preview models**: "intended for evaluation
  purposes only and should not be used in production"; preview models "may be discontinued at short notice".
  Its predecessor `qwen/qwen3.6-27b` was shut down on 2026-09-14.
- Each image counts as 2,048 input tokens; up to 3 images and 20 MB per request; list price $0.80 / $4.00 per
  1M input / output tokens. The rate-limit table shows 30 RPM, 8K TPM, 1K RPD, 200K TPD for this model (the
  page does not label the table clearly as free tier).
- The only other Groq vision model, `meta-models/muse-spark-open`, is enterprise ("contact sales").

## Measurements (qwen2.5vl:7b local, uncached, RapidOCR + Tesseract, strict rule)

| photos | provider | key values READ and correct | wrong READs (key) | located | s/photo total (vision, OCR in parallel) | tokens / photo | cost / photo |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 (spike) | local qwen2.5vl:7b | 12 of 26 | 3 (1) | 19 of 26 | 16.6 (16.6, 7.8) | 1,580 | $0 |
| 35 (all) | local qwen2.5vl:7b | 41 of 94 | 5 (2) | 67 of 94 | 15.8 (15.8, 7.2), max 36.7 | 1,576 | $0 |
| 10 / 35 | Groq qwen/qwen3.8-27b | not measured | not measured | not measured | not measured | about 2,500 expected (2,048 per image + prompt + answer) | about $0.0026 at list price, $0 on the free tier |

Running vision and OCR in parallel brings the local mean from 19.5 s to 15.8 s per photo. The fresh local run
reproduces the committed scores exactly (one field differs only in its box, still DISPUTED).

Expected Groq throughput from the limits alone: about 2,500 tokens per photo against 8K tokens per minute is
about 3 photos per minute (35 photos take at least ~12 minutes), and 200K tokens per day is about 80 photos.

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

T5 is not committed and shares `reader.py`, `vision.py`, `evaluate.py` and `README.md` with this change, so they
cannot be split cleanly. Either one commit `a: tickets and crate labels, optional Groq vision provider (#22)`, or
T5 first with these files as they are now. Your call on "commit".
