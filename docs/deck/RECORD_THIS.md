# Record this — word for word

**Target 2:45. Hard limit 3:00.** Everything in `>` is what you say. Everything
in `[ ]` is what you do. Every number spoken is on screen as you say it.

---

## Before you press record — 90 seconds

1. **Wake the Space.** Open <https://jacklachan-unihack.hf.space> and let it
   finish loading once. A free Space sleeps and takes 20–30 s to wake. Once it
   is warm it loads in about a second.
2. Reload it so the catalogue fills fresh on camera.
3. Terminal open at `C:\Users\mohit\hackathons\unihack\caliper`, cleared.
4. Browser at 100 % zoom, one window, no other tabs, bookmarks bar hidden.
5. Notifications off. Record 1920×1080.
6. Speak slower than feels natural. Pause between sections.

---

## 0:00 — The problem  *(18 s)*

**[ Terminal, full screen. Run: ]**

```bash
head -2 data/input/sample_1000_items.csv
```

> This is what a distributor actually hands over. Six columns. A description
> that reads "49-94-1940 Milw 14 by 1/8 by 1 inch Masonry Cut Off Disc". The
> brand fields say "Unbranded". The supplier listed is a distributor, not the
> manufacturer.
>
> Unilog's delivery format expects two hundred and fifty-two columns back from
> that.

---

## 0:18 — It runs, and it runs fast  *(20 s)*

**[ Run. Let the progress bar finish — do not cut. ]**

```bash
python -m caliper run data/input/sample_1000_items.csv -o data/out
```

> A thousand rows in about three seconds. No API key. No pip install — there
> are zero third-party packages in this pipeline. CSV and XLSX are both read
> and written with the Python standard library.
>
> Out comes the two-hundred-and-fifty-two-column delivery file, a provenance
> ledger, a review queue, and a relationship graph.

**[ Hold on the printed summary for two seconds. ]**

---

## 0:38 — The same thing, hosted  *(14 s)*

**[ Switch to the browser. Reload the Space. Let the catalogue fill. ]**

> That is the same pipeline, hosted, and this is the link the judges get. No
> login, no key, nothing to configure. It enriches a thousand real industrial
> SKUs the moment the page opens — because your first ten seconds should show
> output, not a form.

**[ Let the metric strip land. Point at it. ]**

> Seventy-seven point four percent ready to publish with no human. A hundred
> percent invoice compliance. Ninety-nine point five percent sibling agreement.

---

## 0:52 — The whole argument  *(30 s)*  **← never cut this**

**[ Click the SECOND row, `3MABR-7100075678`. No scrolling needed.
The evidence panel opens directly underneath the table. ]**

> Click any row, and here is the entire argument for this project.
>
> Every populated column shows the method that produced it, the rule that fired,
> a confidence, and — in the gold quote — the exact characters of the input that
> justified the value, with the column they came from.

**[ Point at the BRAND_NAME row. ]**

> Brand name became 3M-trademark under rule I-D-N-B-R-D-oh-one, because the
> characters "3M" appear in Part underscore Desc and resolve against the
> approved brand registry. Confidence nought point eight eight.
>
> Nothing on this screen was generated. Twenty-six thousand five hundred and
> ninety-six populated cells across this catalogue carry provenance exactly like
> this — and it is produced by the pipeline, not written afterwards as a report.

---

## 1:22 — The constraint everybody fails  *(20 s)*

**[ Scroll up slightly to the character-budget solver card. ]**

> Invoice description has a hard ceiling: forty characters, upper case. Ask a
> language model to be brief and you get forty-one characters some of the time.
>
> We solve it as a budget problem instead. Facts are ranked by how much they
> identify the product, each one carries an abbreviation ladder, and the solver
> fits what it can and reports what it dropped.
>
> A hundred percent compliance — by construction, not by luck.

---

## 1:42 — What it found wrong with the supplier's data  *(22 s)*

**[ Click **Findings in the source data**. ]**

> While it enriches, it audits. These are problems in the *supplier's* file, not
> ours. Brands that disagree with the manufacturer. Rows where no approved brand
> could be resolved. Items that break the pattern of their own product family.
>
> A hundred and twenty-three rows abstained from classification rather than
> guess. Abstaining is a feature — a wrong classpath is worse than an empty one,
> because attribute validation is keyed on it.

**[ Click **Induced category specs**. ]**

> And these category rulebooks — which attributes a category has, which of them
> are filterable — were derived from the rows themselves, with a fill rate
> behind every attribute. That is work normally done by hand, one category at a
> time, across tens of thousands of categories.

---

## 2:04 — It works on *your* file  *(22 s)*

**[ Click **Try a file with completely different column names**. ]**

> This file's headers are M-F-R PART hash, Item Description, Make, Vendor Name.
> Nothing like the sample.

**[ Point at the "Columns detected, not assumed" line. ]**

> Column roles are detected, not assumed. Same pipeline, same two hundred and
> fifty-two columns, no configuration.

**[ Click **Download the delivery file**. ]**

> And you leave with the delivery file — header byte-identical to the published
> sheet — plus a review queue ranked by how much each review is actually worth.

---

## 2:26 — The honest number  *(24 s)*  **← the part that earns trust**

**[ Click **How it works**. Let the text sit on screen. ]**

> One last thing, and it matters more than any percentage I have said.
>
> Our accuracy against the published ground truth is forty-eight percent exact —
> measured on **two labelled rows**. Two rows cannot support a claim, so we
> print that base beside the number every single time instead of quoting the
> percentage on its own.
>
> That is also why we measure something needing no labels at all: sibling
> agreement across all one thousand rows. Ninety-nine point five percent, over
> fifteen hundred and sixteen comparisons.
>
> A model never writes a cell here. It can propose a fact that quotes the
> source, or judge a fact that already exists. That boundary is the design — and
> everything you have just seen follows from it.

**[ Scroll to the top. End on the CALIPER header. Hold two seconds. Stop. ]**

---

## If you overrun

Cut in this order:

1. **1:42 – 2:04** — the findings and induced specs section. Costs you the most
   content, but the evidence panel carries the argument alone.
2. **0:18 – 0:38** — the terminal run. The Space shows the same speed.
3. Trim the closing to just the two-labelled-rows sentence.

**Never cut 0:52 – 1:22.** That is the submission.

---

## Numbers you may be asked, with the right answer

Keep these straight if you fumble a line and want to recover:

| | |
|---|---|
| Rows → columns | 1,000 → 252, about 3 seconds |
| Ready to publish unattended | 77.4 % |
| `INVOICE_DESC` ≤ 40 chars | 100 % |
| Brand resolved | 92.5 % |
| Classified | 88.8 % (the rest abstain) |
| Sibling agreement | 99.5 % over 1,516 comparisons |
| Cells with provenance | 26,596 |
| Relationship edges | 614 |
| Category specs induced | 64 |
| Accuracy vs ground truth | 48.0 % exact — **on two labelled rows** |
| Invariant tests | 46 passing |
| Third-party packages | 0 |

---

## Recording notes

- **Say "two labelled rows" out loud.** Volunteering the weak number is the
  single most credible thing in the video.
- Do not speed up the enrichment. Real time is the proof.
- If the Space is cold, stop, let it wake, start again. Never narrate over a
  loading screen.
- Upload **unlisted** to YouTube, or to Drive set to **anyone with the link —
  Viewer**. Check it in a private window before you paste it. A judge hitting a
  permission wall is a failed gate.
