# Demo video script — CALIPER

**Target length: 2 min 50 s.** Screen recording with voiceover. No face cam
needed. Every number spoken is on screen at the same moment, so a judge can
check it as you say it.

This script is written against the **live Space**, which is what the judges will
click:

```
https://huggingface.co/spaces/jacklachan/unihack
```

**Before you hit record**

- **Open the Space and let it finish loading once.** A free Space sleeps after
  ~48 hours idle and takes 20–30 seconds to wake. Wake it, then reload for the
  take, so the catalogue fills in about three seconds on camera.
- Terminal open in the repo, cleared, for the first twenty seconds.
- Have `data/input/foreign_schema_test.csv` where you can drag it.
- Browser at 100 % zoom, one window, no other tabs, bookmarks bar hidden.
- Close Slack and mail. Notifications off.
- Record at 1920×1080. Speak slower than feels natural.

> **Where to click, in one line:** the tabs are **Catalogue and evidence**,
> **Findings in the source data**, **Induced category specs**, **Download the
> delivery file**, **How it works**. The evidence panel is *underneath the
> table on the first tab* — you do not switch tabs to see it.

---

## 0:00 – 0:18 · The problem, in one row

**Screen:** terminal, full screen.

```bash
head -2 data/input/sample_1000_items.csv
```

**Say:**

> This is what a distributor actually hands over. Six columns. The description
> reads `49-94-1940 Milw 14 by 1/8 by 1 inch Masonry Cut Off Disc`, the brand
> fields say "Unbranded", and the supplier listed is a distributor, not the
> maker.
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

> One thousand rows, about three seconds, no API key, and no `pip install` —
> CSV and XLSX are both read and written with the standard library. There are
> zero third-party packages in this pipeline.
>
> Out comes the 252-column delivery file as CSV and XLSX, a provenance ledger,
> a review queue, and a relationship graph.

**Screen:** when the summary prints, hold on it for two full seconds.

---

## 0:38 – 0:52 · The same thing, hosted

**Screen:** switch to the browser and reload the Space. Let the catalogue fill
on camera.

**Say:**

> That is the same pipeline, hosted. No login, no key, nothing to configure —
> it enriches a thousand real industrial SKUs the moment the page opens,
> because a judge's first ten seconds should show output, not a form.

**Screen:** let the metric strip land — 1,000 rows, 77.4 % ready to publish,
100 % invoice compliance, 99.5 % sibling agreement.

---

## 0:52 – 1:22 · The thing that makes it different

**Screen:** in the **Catalogue and evidence** tab, click the row
`49-94-0121` (Milwaukee, Performance+ Metal Cut Off Wheel). The evidence panel
opens directly underneath the table. Scroll down a little.

**Say:**

> Click any row, and this is the whole argument.
>
> Every populated column shows the method that produced it, the rule id, a
> confidence, and — in the gold quote — **the exact characters of the input
> that justified the value**, with the column they came from.
>
> `BRAND_NAME` became Milwaukee-registered-trademark under rule `IDN-BRD-01`,
> because the four characters "milw" appear in `Part_Desc` and resolve against
> the approved brand registry. Nothing on this screen was generated.

**Screen:** hold on the `BRAND_NAME` and `Product Name` cells for two seconds.

**Say:**

> Twenty-six thousand six hundred and twenty-seven populated cells across the
> catalogue carry provenance like this. It is produced by the pipeline — it is
> not a report written afterwards.

---

## 1:22 – 1:42 · The constraint everybody fails

**Screen:** scroll up slightly in the same panel to the
**character-budget solver** card.

**Say:**

> `INVOICE_DESC` has a hard ceiling: forty characters, upper case. Ask a
> language model to "be brief" and you get forty-one characters some of the
> time.
>
> We solve it as a budget problem instead. Facts are ranked by how much they
> identify the product, each one carries an abbreviation ladder, and the solver
> fits what it can and tells you what it dropped. Six facts, thirty-nine of
> forty characters.
>
> One hundred percent compliance, by construction rather than by luck.

---

## 1:42 – 2:04 · What it found wrong with the client's data

**Screen:** click **Findings in the source data**.

**Say:**

> While enriching, it also audits. These are problems in the **supplier's**
> file, not ours — brands that disagree with the manufacturer, rows where no
> approved brand could be resolved, and items that break the pattern of their
> own product family.
>
> A hundred and twenty-three rows abstained from classification rather than
> guess. Abstaining is a feature: a wrong classpath is worse than an empty one,
> because attribute validation is keyed on it.

**Screen:** click **Induced category specs**.

**Say:**

> And these category rulebooks — which attributes a category has, which are
> filterable — were derived from the rows themselves, with a fill rate behind
> every attribute. That is work normally done by hand, one category at a time,
> across tens of thousands of categories.

---

## 2:04 – 2:26 · It works on *your* file

**Screen:** click **Try a file with completely different column names**.

**Say:**

> This file's headers are `MFR PART #`, `Item Description`, `Make`, `Vendor
> Name` — nothing like the sample. Column roles are detected, not assumed.

**Screen:** point at the "Columns detected, not assumed" line as it appears,
then at the metric strip.

**Say:**

> Same pipeline, same 252 columns, no configuration. Drop in your own CSV and
> it does the same thing.

**Screen:** click **Download the delivery file** and show the three downloads.

**Say:**

> And you leave with the delivery file — header byte-identical to the published
> sheet — plus a review queue ranked by how much that review is actually worth.

---

## 2:26 – 2:50 · The honest number

**Screen:** click **How it works** and let the text sit on screen.

**Say:**

> One last thing, because it matters more than any of the percentages.
>
> Our accuracy against the published ground truth is forty-eight percent
> exact — measured on **two labelled rows**. Two rows cannot support a claim,
> so we print that base next to the number every single time instead of quoting
> the percentage alone.
>
> That is also why we measure something that needs no labels at all: sibling
> agreement across all one thousand rows, ninety-nine point five percent over
> fifteen hundred and sixteen comparisons.
>
> A model never writes a cell here. It can propose a fact that quotes the
> source, or judge a fact that already exists. That boundary is the design, and
> everything you just saw follows from it.

**Screen:** end on the hero — CALIPER, "measures what it claims, and refuses to
write what it cannot support."

---

## If you need to cut to 2:00

Drop, in this order:

1. **1:42 – 2:04** (findings and induced specs) — strongest content to lose, but
   the evidence panel carries the argument alone.
2. **0:18 – 0:38** (the terminal run) — the Space demonstrates the same speed.
3. Shorten the closing to just the two-labelled-rows sentence, which is the part
   that earns trust.

**Never cut 0:52 – 1:22.** The evidence panel is the submission.

---

## Recording notes

- Say "two labelled rows" out loud. Volunteering the weak number is the single
  most credible thing in the video.
- Do not speed up the enrichment. Real time is the proof.
- If the Space is cold and takes 25 seconds, stop, let it wake, and start again.
  Do not narrate over a loading screen.
- Upload unlisted to YouTube or Drive. If Drive, set sharing to **anyone with
  the link — Viewer** and check it in a private window. A judge hitting a
  permission wall is a failed gate.
