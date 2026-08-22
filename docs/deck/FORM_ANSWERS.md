# Submission form — what to paste where

Fields as they appear on the Hack2Skill form.

---

## Upload your Prototype deck/presentation *(PDF, max 5 MB)*

**File:** `docs/deck/CALIPER_UniHack.pdf` — 0.40 MB, 10 slides.

The form takes PDF only, so upload the `.pdf`, not the `.pptx`. Both are in the
repo; regenerate either with:

```bash
python docs/deck/build_deck.py     # rebuilds the .pptx
```

---

## Provide a brief overview of your solution and how it solves the problem *(2056 chars)*

Paste the block below. Verified at **2,013 characters**, inside the 2,056 limit.

---

CALIPER turns a messy supplier row into Unilog's 252-column delivery format, and can show you why it wrote every cell.

Most pipelines hand a row to a language model and validate afterwards. CALIPER makes that structurally impossible. Every extractor — rules, the brand registry, taxonomy, family consensus, and the model — writes into one typed Product Fact Graph, where a fact without evidence is rejected at insertion. Composition, validation and export only read from it. The model may never write an output cell: it can propose a fact that quotes the source, or render a verdict on facts that already exist. That one-way boundary means the five description formats cannot contradict each other, and 26,627 populated cells each carry the rule that produced them and the characters that justified them.

On the 1,000-row sample it enriches in about nine seconds with no API key and no third-party packages: 92.5% of rows resolved to an approved brand, 88.8% classified (the rest abstain rather than guess), 77.4% ready to publish unattended. INVOICE_DESC hits 100% compliance with its 40-character upper-case ceiling because the limit is solved as a budget problem — facts ranked by how much they identify the product, each with an abbreviation ladder — rather than requested of a model.

Three findings came from measuring the data, and each changed the build. Unilog's own answer key fills only 63 of 252 columns, so we calibrate our fill rate against it instead of maximising — over-filling is fabrication. Eleven of the twelve attribute values in the labelled row appear nowhere in its input, an honest ceiling without manufacturer retrieval. And our own physical guardrail caught a parser bug, reporting an arbor hole wider than the wheel it was cut in.

Accuracy against the published ground truth is 48.0% exact, on two labelled rows — a narrow base we print beside every rate. So we also measure sibling agreement across all 1,000 rows: 99.5% over 1,516 comparisons.

---

## Share the link to your live prototype demonstrating the core functionality *(1024 chars)*

```
https://huggingface.co/spaces/<YOUR-USERNAME>/caliper
```

Follow `deploy/DEPLOY.md` to put this up. **Open it in a private window before
you submit** — it must load without a login.

Optionally append, if there is room:

> Opens on 1,000 enriched SKUs. Click any row, then any cell, to see the rule
> and the source characters behind that value. Upload your own CSV — column
> names are detected, not assumed.

---

## Share the GitHub Repository link

```
https://github.com/jacklachan/unihack
```

---

## Upload or share the link to a short demo video *(1024 chars)*

Record from `docs/deck/DEMO_SCRIPT.md` (2 min 45 s, shot-by-shot). Upload
unlisted to YouTube or Drive and paste the link.

**If sharing from Google Drive, set the link to “Anyone with the link — Viewer”
and check it in a private window.** A judge hitting a permission wall is a
failed gate.

---

## Challenges *(dropdown)*

Select **AI-Powered Product Intelligence for Industrial Commerce**.

---

## Final check before you press Submit

- [ ] PDF uploads and previews correctly *(not the .pptx)*
- [ ] Overview text pasted whole, under the 2056 limit
- [ ] Live prototype link opens in a **private window**, no login
- [ ] GitHub link opens and the README renders
- [ ] Demo video link plays in a **private window**
- [ ] Challenge dropdown selected
