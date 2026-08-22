# Demo video script — CALIPER

**Target length: 2 min 45 s.** Screen recording with voiceover. No face cam needed.
Every number spoken is on screen at the same moment, so a judge can check it.

**Before you hit record**

```bash
cd caliper
python -m caliper serve          # leave it running on 127.0.0.1:8765
```

- Browser at 100% zoom, one window, no other tabs, bookmarks bar hidden.
- Have `data/input/foreign_schema_test.csv` on the desktop, ready to drag.
- Have a terminal open in the repo, cleared.
- Close Slack/mail. Notifications off.
- Record at 1920×1080. Speak slower than feels natural.

---

## 0:00 – 0:18 · The problem, in one row

**Screen:** terminal, full screen. Type (or paste) this and let it print:

```bash
head -2 data/input/sample_1000_items.csv
```

**Say:**

> This is what a distributor actually hands over. Six columns. The description
> is `49-94-1940 Milw 14 by 1/8 by 1 inch Masonry Cut Off Disc`, the brand
> fields say "Unbranded", and the supplier is a distributor, not the maker.
>
> Unilog's delivery format wants **252 columns** back from that.

---

## 0:18 – 0:38 · It runs, and it runs fast

**Screen:** same terminal.

```bash
python -m caliper run data/input/sample_1000_items.csv -o data/out
```

Let the progress bar run. Do not cut — the speed is the point.

**Say:**

> One thousand rows, nine seconds, no API key, and no pip install — CSV and
> XLSX are both read and written with the standard library.
>
> Out comes the 252-column delivery file as CSV and XLSX, a provenance ledger,
> a review queue, and a relationship graph.

**Screen:** when the summary prints, hold on it for two full seconds.

---

## 0:38 – 1:05 · The thing that makes it different

**Screen:** switch to the browser, **Catalogue** tab. Click the row for
`49-94-1940`. The inspector opens. Click the `SHORT_DESC` cell to expand it.

**Say:**

> Here is the same row enriched. And here is the part that matters — click any
> cell and it tells you where the value came from.
>
> Brand is `Milwaukee` with the registered symbol, resolved from the string
> "Milw" against the approved list. The dimensions came from rule `DIM-CHN-01`,
> and it shows you the exact characters of the input it read them from.

**Screen:** scroll the inspector so `ATTRIBUTE_VALUE 1` and its rule id are visible.

**Say:**

> Twenty-six thousand cells, every one traceable. Not a log file — this is how
> the product is built. **The model is never allowed to write an output cell.**
> It can propose a fact, and the fact has to quote the source, or it is thrown
> away.

---

## 1:05 – 1:25 · The constraint everybody fails

**Screen:** in the same inspector, scroll to the **character-budget solver**
panel so the invoice line and its trace are on screen.

**Say:**

> `INVOICE_DESC` has a hard forty-character ceiling, in capitals. Asking a
> model to "keep it under forty" fails quietly.
>
> Here it is a budget problem. Facts are ranked by how much they identify the
> product, each one has an abbreviation ladder — Stainless Steel, S-S-T, S-S —
> and the solver fits what it can. It shortens before it drops, and it drops
> before it overflows.
>
> Thirty-five of forty characters, five facts kept. **One hundred percent
> compliance across the catalogue, by construction.**

---

## 1:25 – 1:50 · What it found wrong with the client's data

**Screen:** click **Overview**. Scroll to *Findings raised against the source
catalogue*.

**Say:**

> It also reports what is wrong with the data it was given. Rows where the
> brand and the manufacturer disagree. Rows where it refused to guess a
> category rather than inventing one.

**Screen:** scroll up slightly to the **Fill rate** panel.

**Say:**

> And this is the number I would look at first. Unilog's own answer key fills
> sixty-three of two hundred and fifty-two columns — about a quarter. UPC,
> UNSPSC, dimensions, country of origin are blank in the published answer.
>
> So a pipeline that fills ninety percent of the sheet is inventing two-thirds
> of a catalogue. We calibrate against the answer key instead of maximising.

---

## 1:50 – 2:10 · It works on *your* file

**Screen:** click **Upload catalogue**. Drag in `foreign_schema_test.csv`.
Let the progress bar run to completion.

**Say:**

> The brief says the prototype has to handle the evaluation dataset, so it must
> not be wired to the sample's headers. This file has different column names, a
> different order, and two junk columns.
>
> `MFR PART #` maps to part number, `Item Description` to description, `Make` to
> brand, `Vendor Name` to manufacturer — and quantity-on-hand is ignored.

**Screen:** when the board reloads, point at brand resolved and classified.

**Say:**

> Ninety-seven percent brand resolution on headers it has never seen.

---

## 2:10 – 2:32 · The honest number

**Screen:** terminal.

```bash
python -m caliper eval "" --truth data/reference/delivery_format_sample.csv -o data/out
```

**Say:**

> Against the published ground truth we score forty-eight percent exact on
> in-scope fields — and that is on **two labelled rows**, which we print beside
> every rate rather than hiding.
>
> Brand, classpath, department, product name and part number are all at one
> hundred. What is missing is attribute *values* — and we can prove why. The
> labelled dishwasher's input is thirty-nine characters, and eleven of its
> twelve attribute values appear nowhere in it. They need the manufacturer's
> own source. That is a ceiling in the data, not a missing rule.

**Screen:** switch to browser Overview, point at **Sibling agreement 99.5%**.

**Say:**

> So we measure something we *can* ask of all thousand rows: products in the
> same family must agree about the facts they share. Ninety-nine and a half
> percent across fifteen hundred comparisons.

---

## 2:32 – 2:45 · Close

**Screen:** Overview, full page, still.

**Say:**

> Every number you have seen was produced by a run, and then we went and read
> the outputs behind it — which is how we found three bugs in our own parser.
>
> Enrichment is table stakes. Knowing which rows you can ship without a human,
> and being able to prove why, is the product.
>
> Seventy-seven percent of this catalogue is ready to publish unattended. The
> rest is queued, ranked by how many SKUs each decision fixes.

**Screen:** last frame — hold on the repo URL for three seconds.

---

## Numbers spoken, for checking against the recording

| Claim | Value | Where it shows on screen |
|---|---|---|
| Rows / time | 1,000 in ~9 s | terminal summary |
| Delivery columns | 252 | terminal summary |
| Provenance cells | 26,627 | Overview → Provenance |
| Invoice compliance | 100 % | Overview → Character limits |
| Budget trace | 35/40, 5 facts | inspector |
| Brand resolved | 92.5 % | Overview → Resolution |
| Classified | 88.8 % | Overview → Resolution |
| Ready to publish | 77.4 % (774) | Overview → hero |
| Foreign-schema brand | 97.5 % | after the upload |
| Accuracy | 48.0 % on 2 rows | eval output |
| Sibling agreement | 99.5 % / 1,516 | Overview → Integrity |
| Answer-key fill | 63–71 of 252 | Overview → Fill rate |

## If you have to cut to 2 minutes

Drop **1:50 – 2:10** (the foreign-schema upload) and shorten the close. Keep the
evidence panel and the budget solver — they are the only two things no other
submission will have.

## Do not

- Do not speed up or cut the enrichment run. Its speed is a claim; let it prove itself.
- Do not read the slides aloud. The deck is a separate gate.
- Do not say "as you can see" — point instead.
- Do not claim a number the screen is not showing at that moment.
