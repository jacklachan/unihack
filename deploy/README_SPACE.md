---
title: CALIPER
emoji: 📐
colorFrom: indigo
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Evidence-bound product intelligence for industrial commerce
---

# CALIPER

**Evidence-bound product intelligence.** *Measured, not guessed.*

Built for **UniHack** — Unilog's AI-Powered Product Intelligence challenge.

A distributor hands over six columns. The delivery format expects **252** back.
This turns one into the other, and every value it writes can be traced to the
rule that produced it and the characters of the input that justified it.

## Try it

The Space opens on a catalogue of 1,000 real industrial SKUs, already enriched.

1. **Catalogue** → click any row → click any cell. That is the evidence panel:
   method, rule id, the exact source substring, and confidence.
2. **Overview** → the character-limit panel. `INVOICE_DESC` has a hard
   40-character ceiling in caps, solved as a budget problem rather than asked of
   a model. **100% compliance.**
3. **Overview** → *Findings raised against the source catalogue*. Problems in
   the supplier's data, not ours.
4. **Upload catalogue** → drop in your own CSV. Column names are detected, not
   assumed.
5. **Export delivery CSV** → the 252-column file, header byte-identical to the
   published sheet.

## Running with a model

The first screen offers two modes.

**Deterministic only** needs nothing — rules, registries and induced category
specs produce all 252 columns with no network call.

**Deterministic + AI** takes your own key (Groq, Gemini, Anthropic or OpenAI)
and uses a model *only* on rows the rules could not resolve. The key is held in
the running process's memory for the session, never written to disk, never
logged, and never returned to the browser. Close the Space and it is gone.

The model is never permitted to write an output cell. It may propose a fact
that quotes the source — anything unquoted is discarded — or render a verdict
on facts that already exist.

## What it reports about itself

| | |
|---|---|
| Rows → columns | 1,000 → 252, in about 9 seconds |
| Brand resolved to an approved name | 92.5 % |
| Classified | 88.8 % — the rest abstain rather than guess |
| `INVOICE_DESC` ≤ 40 chars, upper case | **100 %** |
| Ready to publish unattended | 77.4 % |
| Sibling agreement | 99.5 % over 1,516 comparisons |
| Traceable cells | 26,627 |
| Third-party packages | **0** |

Accuracy against the published ground truth is 48.0 % exact on in-scope
fields — measured on **two labelled rows**, which is a narrow base and is
printed beside every rate rather than hidden.

## Source

[github.com/jacklachan/unihack](https://github.com/jacklachan/unihack) — 42
invariant tests, standard library only, clone and run.
