# Deck notes: reader speed, cost and privacy (for #35)

Measured 2026-11-25 on the 35 tuning photos. Counts are agreement with AI-read labels until a person has
checked them.

**Headline: a strict rule, not a bigger model.** A field counts as read only when local OCR finds the same
characters printed on the photo. That rule is what keeps wrong readings down, so the vision model can be the
fast one.

- Vision model: `qwen/qwen3.8-27b` on Groq. 5.3 s per check (Groq answers in about 1.1 s; local OCR, run in
  parallel, sets the pace), no GPU needed, so it deploys on a CPU-only server.
- Cost: about $0.0025 per check at Groq's list price (about 2,150 tokens); $0.00 on the free tier.
- Accuracy: 39 of 94 key values read and correct, 3 key wrong READs. Two of the three are cases a local 7B
  model also gets wrong (a MODEL vs CAT. NO. plate, a multi-row rating table) and one is a label gap (a current
  printed on an unreadable plate but not labelled). Every invented value seen in testing was stopped by the rule.
- Privacy: a photo goes to Groq only after the on-device face check; a photo with a face is never sent. No GPS,
  no names.
- If Groq is down, every field is marked DISPUTED (`vision_unavailable`): the system says it could not read,
  it never guesses.
- Risk to state: `qwen/qwen3.8-27b` is a Groq preview model ("evaluation purposes only", may be discontinued at
  short notice; its predecessor was shut down on 2026-09-14). The model is one setting; an offline mode runs
  `qwen2.5vl:7b` locally on a GPU.
- Free-tier throughput: 8,000 tokens per minute is about 3 checks per minute, about 90 per day.

Supporting evidence (same rule, same OCR, two models):

| Vision model | Seconds per check | Cost per check | Key values READ and correct | Key wrong READs |
| --- | --- | --- | --- | --- |
| qwen/qwen3.8-27b, Groq | 5.3 | $0.0025 list, $0 free tier | 39 of 94 | 3 |
| qwen2.5vl:7b, local GPU (offline mode) | 15.8 | $0 | 41 of 94 | 2 |
