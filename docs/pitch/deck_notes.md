# Deck notes: reader speed, cost and privacy (for #35)

Measured 2026-11-25 on the 35 tuning photos with the same strict READ rule and the same local OCR for both
providers. Counts are agreement with AI-read labels until a person has checked them.

| Provider | Where it runs | Seconds per check (mean / max) | Cost per check | Key values READ and correct | Key wrong READs |
| --- | --- | --- | --- | --- | --- |
| qwen2.5vl:7b via Ollama | the laptop (RTX 4050) | 15.8 / 36.7 | $0.00 | 41 of 94 | 2 |
| qwen/qwen3.8-27b via Groq | Groq cloud | 5.3 / 8.3 | $0.0025 at list price; $0.00 on the free tier | 39 of 94 | 3 |

- Groq answers in about 1.1 s; local OCR (about 5 s) then sets the pace, because vision and OCR run in parallel.
- The 2-3 key wrong READs are label disagreements (a plate's MODEL field where the label keeps the catalog
  number, an unlabelled current on an unreadable plate, a multi-row rating table), not invented values. Every
  invented value seen in testing was stopped by the "OCR must find it on the photo" rule.
- Default: local on the laptop (photos never leave it). The deployed server has no GPU and uses Groq.
- Privacy: a photo goes to Groq only after the on-device face check passes; a photo with a face is never sent.
- If Groq fails, every field is marked DISPUTED with reason `vision_unavailable`: the system says it could not
  read, it never guesses.
- Risk to state on the slide: `qwen/qwen3.8-27b` is a Groq preview model ("evaluation purposes only", may be
  discontinued at short notice; its predecessor was shut down on 2026-09-14). The model name is one setting,
  and local qwen2.5vl:7b is the fallback where a GPU is available.
- Throughput on Groq's free tier: about 2,150 tokens per check against 8,000 tokens per minute, so about 3
  checks per minute and about 90 per day.
