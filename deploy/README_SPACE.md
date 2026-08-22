---
title: CALIPER
emoji: 📐
colorFrom: indigo
colorTo: yellow
sdk: gradio
sdk_version: 6.25.0
app_file: app.py
python_version: "3.12"
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

## Try it in this order

The Space enriches 1,000 real industrial SKUs the moment it opens — no button,
no setup, no key.

1. **Catalogue and evidence** → click any row. The panel underneath it shows
   every populated column with its method, its rule id, the exact source
   substring behind it, and a confidence. *This is the thing to look at.*
2. Notice the **character-budget solver** card at the top of that panel: what it
   fitted into `INVOICE_DESC`, what it abbreviated, and what it dropped.
3. **Findings in the source data** → problems in the supplier's file, not ours.
4. **Induced category specs** → Unilog-style category rulebooks derived from the
   rows themselves, with a fill rate behind every attribute.
5. **Try a file with completely different column names** → the same pipeline on a
   file whose headers are `MFR PART #`, `Item Description`, `Make`. Column roles
   are detected, not assumed.
6. Upload your own CSV, then **Download the delivery file** — 252 columns, header
   byte-identical to the published sheet.

## Running it with a model

The deterministic path needs nothing: rules, registries and induced category
specs produce all 252 columns with no network call at all.

Tick **"Also use a model"** and paste your own key (Groq, Gemini, Anthropic or
OpenAI) to add recall on rows the rules could not resolve. The key is held in the
running process's memory for that request only — never written to disk, never
logged, never returned to the browser.

**The model is never permitted to write an output cell.** It can propose a fact
that quotes the source — anything whose quote is not in the input is discarded —
or render a verdict on facts that already exist. If your key is out of quota, the
run says so and continues deterministically rather than failing.

## What it reports about itself

| | |
|---|---|
| Rows → columns | 1,000 → 252, in about 3 seconds |
| Brand resolved to an approved name | 92.5 % |
| Classified | 88.8 % — the rest abstain rather than guess |
| `INVOICE_DESC` ≤ 40 chars, upper case | **100 %** |
| Ready to publish unattended | 77.4 % |
| Sibling agreement | 99.5 % over 1,516 comparisons |
| Traceable cells | 26,596 |
| Third-party packages in the pipeline | **0** |

Accuracy against the published ground truth is 48.0 % exact on in-scope
fields — measured on **two labelled rows**, which is a narrow base and is printed
beside every rate rather than hidden behind the percentage.

## Source

[github.com/jacklachan/unihack](https://github.com/jacklachan/unihack) — 42
invariant tests, standard library only, clone and run.
