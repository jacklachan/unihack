# Record this — word for word

**Target 2:45. Hard limit 3:00.** Everything in `>` is what you say. Everything
in `[ ]` is what you do. Every number spoken is on screen as you say it.

**Commands are PowerShell** (Windows). They were run and verified today.

One product carries the whole video: `DCB518ASTS06G`, the Diablo sanding belt.
It is the first data row of the file *and* the first row of the table, so you
open on the raw input and click the same product later — no scrolling, no
searching.

---

## Before you press record — 90 seconds

1. **Wake the Space.** Open <https://jacklachan-unihack.hf.space> and let it
   finish loading once. A sleeping Space takes 20–30 s to wake; warm, it loads
   in about a second.
2. Reload it so the catalogue fills fresh on camera.
3. PowerShell open, and **run this first so you are in the right folder**:
   ```powershell
   cd C:\Users\mohit\hackathons\unihack\caliper
   ```
   Then clear the screen with `cls` so the recording starts clean.
4. Browser at 100 % zoom, one window, no other tabs, bookmarks bar hidden.
5. Notifications off. Record 1920×1080.
6. Speak slower than feels natural. Pause between sections.

---

## 0:00 — The problem  *(20 s)*

**[ PowerShell, full screen. Run: ]**

```powershell
Get-Content data\input\sample_1000_items.csv -TotalCount 2
```

**[ Two lines print: the header, then the Diablo row. ]**

> This is what a distributor actually hands over. Six columns.
>
> The description reads "Diablo, one-half by eighteen inch, Sanding Belt, six
> pack". All three brand fields say unbranded — no brand, no Unilog brand, no
> DIB brand. And the manufacturer column says "Freud Inc, bracket two-four-three-five" —
> a distributor's internal code, not a clean company name.
>
> Unilog's delivery format expects two hundred and fifty-two columns back from
> that.

---

## 0:20 — It runs, and it runs fast  *(20 s)*

**[ Run. Let the progress bar finish — do not cut. ]**

```powershell
python -m caliper run data\input\sample_1000_items.csv -o data\out
```

> A thousand rows in under four seconds. No API key. No pip install — there are
> zero third-party packages in this pipeline. CSV and XLSX are both read and
> written with the Python standard library.

**[ The summary block prints. Hold on it for two full seconds. ]**

> Ninety-two and a half percent of rows resolved to an approved brand.
> Eighty-eight point eight percent classified. A hundred percent of invoice
> descriptions inside their forty-character limit. And out comes the delivery
> file, a provenance ledger of twenty-six and a half thousand cells, a review
> queue, and a relationship graph.

---

## 0:40 — The same thing, hosted  *(14 s)*

**[ Switch to the browser. Reload the Space. Let the catalogue fill. ]**

> That is the same pipeline, hosted — and this is the link the judges get. No
> login, no key, nothing to configure. It enriches a thousand real industrial
> SKUs the moment the page opens, because your first ten seconds should show
> output, not a form.

**[ Point at the line above the metrics that names the file. ]**

> It tells you what it just ran and when. This is that same thousand-row sample,
> enriched on page load — not prepared earlier.

**[ Point at the first row of the table. ]**

> And there is our sanding belt. Every brand field in the source said
> "unbranded". The brand column here says Diablo, registered trademark.

---

## 0:54 — The whole argument  *(32 s)*  **← never cut this**

**[ Click the FIRST row, `DCB518ASTS06G`. The evidence panel opens directly
underneath the table. No scrolling needed. ]**

> Click the row, and here is the entire argument for this project.
>
> Every populated column shows the method that produced it, the rule that fired,
> a confidence, and — in the gold quote — the exact characters of the input that
> justified the value, with the column they came from.

**[ Point at BRAND_NAME. ]**

> Brand name became Diablo, registered trademark, under rule
> I-D-N-B-R-D-oh-one. The evidence is the word "Diablo", found in Part
> underscore Desc, resolved against the approved brand registry. Confidence
> nought point eight eight.

**[ Point at MANUFACTURER_NAME. ]**

> And the manufacturer — which arrived as "Freud Inc" with a distributor code
> bolted on — came out as "Freud America, Incorporated", the approved corporate
> name.
>
> Nothing on this screen was generated. Twenty-six thousand five hundred and
> ninety-six populated cells across this catalogue carry provenance exactly like
> this, and it is produced by the pipeline — not written afterwards as a report.

---

## 1:26 — The constraint everybody fails  *(20 s)*

**[ Scroll up slightly in the panel to the character-budget solver card. ]**

> Invoice description has a hard ceiling: forty characters, upper case. Ask a
> language model to be brief and you get forty-one characters some of the time.
>
> We solve it as a budget problem instead. Facts are ranked by how much they
> identify the product, each one carries an abbreviation ladder, and the solver
> fits what it can and reports what it dropped. Here, three facts into
> twenty-seven of forty characters.
>
> A hundred percent compliance — by construction, not by luck.

---

## 1:46 — What it found wrong with the supplier's data  *(22 s)*

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

## 2:08 — It works on *your* file  *(20 s)*

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

## 2:28 — The honest number  *(22 s)*  **← the part that earns trust**

**[ Click **How it works**. Let the text sit on screen. ]**

> One last thing, and it matters more than any percentage I have said.
>
> Our accuracy against the published ground truth is forty-eight percent exact —
> measured on **two labelled rows**. Two rows cannot support a claim, so we
> print that base beside the number every time, instead of quoting the
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

1. **1:46 – 2:08** — findings and induced specs. Costs the most content, but the
   evidence panel carries the argument alone.
2. **0:20 – 0:40** — the terminal run. The Space shows the same speed.
3. Trim the closing to just the two-labelled-rows sentence.

**Never cut 0:54 – 1:26.** That is the submission.

---

## Numbers, if you fumble and need to recover

| | |
|---|---|
| Rows → columns | 1,000 → 252, under 4 seconds |
| Ready to publish unattended | 77.4 % (774 rows) |
| `INVOICE_DESC` ≤ 40 chars | 100 % |
| Brand resolved | 92.5 % |
| Classified | 88.8 % (the rest abstain) |
| Sibling agreement | 99.5 % over 1,516 comparisons |
| Cells with provenance | 26,596 |
| Relationship edges | 614, linking 60 % of products |
| Category specs induced | 64 |
| Product families found | 578 |
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
