# Submission form — what to paste where

Fields as they appear on the Hack2Skill form.

---

## Upload your Prototype deck/presentation

**File:** `docs/deck/CALIPER_UniHack.pdf` — 0.81 MB, 18 slides.

Built on the organisers' **mandatory template**, used as supplied: every slide
keeps its background artwork, header bar and heading. Only the empty body area
was filled, plus screenshots of the running prototype.

Upload the **PDF** if the form takes PDF; upload `CALIPER_UniHack.pptx` if it
wants the editable deck. Both are in `docs/deck/`. Rebuild either with:

```bash
python docs/deck/build_template_deck.py
```

Team **Lord of the Ping**, led by **L Mohit Jain**, is filled in on slide 2.

Slides 15–17 answer the questions a judge is most likely to push on — the
two-labelled-rows base, why not just prompt a model, brittleness, scale, cost,
data leaving the network — so the weak points are addressed before they are
raised rather than after.

### One thing you must still fill in

- **Slide 14** — the demo video link, marked in **red** so you cannot miss it.

## Provide a brief overview of your solution and how it solves the problem *(2056 chars)*

Paste the block below. Verified at **2,013 characters**, inside the 2,056 limit.

---

CALIPER turns a messy supplier row into Unilog's 252-column delivery format, and can show you why it wrote every cell.

Most pipelines hand a row to a language model and validate afterwards. CALIPER makes that structurally impossible. Every extractor — rules, the brand registry, taxonomy, family consensus, and the model — writes into one typed Product Fact Graph, where a fact without evidence is rejected at insertion. Composition, validation and export only read from it. The model may never write an output cell: it can propose a fact that quotes the source, or render a verdict on facts that already exist. That one-way boundary means the five description formats cannot contradict each other, and 26,596 populated cells each carry the rule that produced them and the characters that justified them.

On the 1,000-row sample it enriches in about nine seconds with no API key and no third-party packages: 92.5% of rows resolved to an approved brand, 88.8% classified (the rest abstain rather than guess), 77.4% ready to publish unattended. INVOICE_DESC hits 100% compliance with its 40-character upper-case ceiling because the limit is solved as a budget problem — facts ranked by how much they identify the product, each with an abbreviation ladder — rather than requested of a model.

Three findings came from measuring the data, and each changed the build. Unilog's own answer key fills only 63 of 252 columns, so we calibrate our fill rate against it instead of maximising — over-filling is fabrication. Eleven of the twelve attribute values in the labelled row appear nowhere in its input, an honest ceiling without manufacturer retrieval. And our own physical guardrail caught a parser bug, reporting an arbor hole wider than the wheel it was cut in.

Accuracy against the published ground truth is 48.0% exact, on two labelled rows — a narrow base we print beside every rate. So we also measure sibling agreement across all 1,000 rows: 99.5% over 1,516 comparisons.

---

## Share the link to your live prototype demonstrating the core functionality *(1024 chars)*

```
https://huggingface.co/spaces/jacklachan/unihack
```

**This is live and verified.** It loads without a login and enriches 1,000 SKUs
on open. Check it in a private window on the morning of judging — a free Space
sleeps after ~48 hours idle and takes 20–30 seconds to wake.

Append this if there is room, because it tells the judge where to click:

> Opens on 1,000 enriched SKUs — no button, no key, no setup. Click any row to
> see, for every populated column, the rule that produced it and the exact
> characters of the input that justified it. Upload your own CSV: column roles
> are detected, not assumed.

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

- [ ] **Slide 14: demo video link pasted** *(red on the slide)*
- [ ] Deck uploads and previews correctly
- [ ] Overview text pasted whole, under the 2056 limit
- [ ] Live prototype opens in a **private window**, no login, and the
      catalogue fills on its own
- [ ] GitHub link opens and the README renders
- [ ] Demo video link plays in a **private window**
- [ ] Challenge dropdown selected
