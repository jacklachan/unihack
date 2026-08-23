# Record this

**Target 2:45. Hard limit 3:00.** Read the `>` lines. Do the `[ ]` lines.

One product carries the whole video: a **Diablo sanding belt**. It's the first
row of the file *and* the first row of the table — so you open on the mess, and
click the same product later to show it cleaned up. No scrolling, no searching.

Talk like you're showing this to a friend who's about to be impressed. Short
sentences. Let the pauses do work.

---

## Before you press record

1. **Wake the Space** — open <https://jacklachan-unihack.hf.space>, let it load
   once. Cold it takes 20–30 s; warm it's about a second. Then reload it.
2. PowerShell, then **run this or nothing else will work**:
   ```powershell
   cd C:\Users\mohit\hackathons\unihack\caliper
   ```
   Your prompt must end in `...\caliper>`. Then `cls`.
3. Browser at 100 %, one window, no other tabs, no bookmarks bar.
4. Notifications off. 1920×1080.

---

## 0:00 — The mess  *(22 s)*

**[ PowerShell, full screen. Run: ]**

```powershell
Get-Content data\input\sample_1000_items.csv -TotalCount 2
```

> Okay. This is a real product, from a real distributor. Somewhere in that line
> is a brand, a size, and a category.
>
> Three separate columns exist to tell you the brand. All three say
> "unbranded". The manufacturer field says "Freud Inc" — with a random number
> stapled to the end of it.

**[ Beat. ]**

> Unilog needs two hundred and fifty-two columns out of that. Brand with the
> right trademark symbol. Five different descriptions, each with its own rules.
> A full attribute list.
>
> Right now, a person does this. By hand. For millions of products.

---

## 0:22 — Watch  *(18 s)*

**[ Run it. Let the bar fill. Say nothing until it finishes. ]**

```powershell
python -m caliper run data\input\sample_1000_items.csv -o data\out
```

> A thousand products. Under four seconds.
>
> No API key. Nothing installed. This thing has *zero* dependencies — it's
> written entirely in Python's standard library. You could run it on a laptop
> with the wifi switched off.

**[ Point at the summary. ]**

> Ninety-two percent of them found their real brand. Every single invoice line
> came out inside its character limit. And nobody typed anything.

---

## 0:40 — Same thing, but you can click it  *(14 s)*

**[ Browser. Reload the Space. Let the catalogue fill. ]**

> That's the same engine, live on the internet. This is the link the judges get.
> No login. No key. Nothing to set up.
>
> It starts working the second the page opens — because I'd rather show you
> something than show you a file picker.

**[ Point at the first row. ]**

> And there's our sanding belt. Every brand field said "unbranded".
>
> It says Diablo.

---

## 0:54 — The receipts  *(34 s)*  **← this is the video. Never cut it.**

**[ Click the FIRST row, `DCB518ASTS06G`. The panel opens right underneath. ]**

> Now — here's the thing.
>
> Any AI can fill in two hundred and fifty-two columns. That's the easy part.
> The problem is you have no idea which ones it just made up. And a made-up
> product spec looks *exactly* like a real one.

**[ Beat. Let the panel sit. ]**

> So every value in here comes with a receipt.

**[ Point at BRAND_NAME. ]**

> Brand: Diablo. Why? Because the word "Diablo" is sitting right there in the
> description — that's the highlighted bit — and it matched the approved brand
> list. It's eighty-eight percent confident, and it'll tell you that too.

**[ Point at MANUFACTURER_NAME. ]**

> Manufacturer came in as "Freud Inc" plus junk. It came out as "Freud America,
> Incorporated" — the actual company name.
>
> Twenty-six thousand cells in this catalogue. Every one of them can do this.
> Not a report we generated afterwards — this *is* how it works.

---

## 1:28 — Forty characters  *(20 s)*

**[ Scroll up a touch to the character-budget card. ]**

> Quick one. The invoice line has a hard limit: forty characters, all caps.
>
> Ask a language model to "keep it short" and it'll hand you forty-one
> characters and a shrug.

**[ Beat. ]**

> So we don't ask. We treat it like packing a suitcase. Rank everything by how
> much it actually identifies the product, pack until it's full, and tell you
> what got left behind. Three facts, twenty-seven characters, done.
>
> A hundred percent. Every time. Not because it got lucky — because it can't
> not.

---

## 1:48 — It starts snitching  *(20 s)*

**[ Click **Findings in the source data**. ]**

> Here's the part nobody asked for.
>
> While it was working, it started finding problems — in the *supplier's* file.
> Brands that contradict the manufacturer. Products that don't match the rest of
> their own family.
>
> And a hundred and twenty-three products where it just went: I don't know what
> this is. So it left it blank and flagged it. Because a confidently wrong
> category is worse than an honest gap.

**[ Click **Induced category specs**. ]**

> Oh, and these? Category rulebooks. Which attributes matter, which ones you can
> filter on. It worked those out by itself, from the data. That's normally a
> human job. Tens of thousands of times over.

---

## 2:08 — Your file, not ours  *(20 s)*

**[ Click **Try a file with completely different column names**. ]**

> "Sure, but it only works on your file."
>
> This one's headers are M-F-R PART hash, Item Description, Make, Vendor Name.
> Nothing in common with the last one.

**[ Point at the detected-columns line. ]**

> It figured out what each column was. Same two hundred and fifty-two columns
> out the other end. Nothing configured.

**[ Click **Download the delivery file**. ]**

> And you walk away with the finished file — plus a to-do list of the rows worth
> a human's time, sorted by how much that time is worth.

---

## 2:28 — The honest bit  *(20 s)*  **← the part that wins it**

**[ Click **How it works**. ]**

> Last thing. And this is the part I actually want you to remember.
>
> Our accuracy against the official answer key is forty-eight percent.

**[ Beat. Don't rush this. ]**

> Measured on two rows. Two. That's the entire answer key that shipped with this
> challenge.
>
> Two rows can't prove anything — so we print that next to the number every
> single time, instead of quietly saying "forty-eight percent" and moving on.
>
> And it's why we measure something that doesn't need an answer key at all:
> whether the thing agrees with itself across all thousand products. Ninety-nine
> and a half percent.
>
> The AI here never writes a single value. It can point at something in the
> text, or double-check something we already found. That's it. That's the whole
> idea — and everything you just watched falls out of it.

**[ Scroll to the top. Hold on the CALIPER header. Two seconds. Stop. ]**

---

## Running long?

Cut in this order: **1:48–2:08** (the findings bit) → **0:22–0:40** (the
terminal) → trim the ending to just the two-rows line.

**Never cut 0:54–1:28.** That's the whole submission.

---

## Numbers, if you lose your place

| | |
|---|---|
| Speed | 1,000 products → 252 columns, under 4 seconds |
| Needs no human | 77.4 % (774 of 1,000) |
| Invoice line within 40 chars | 100 % |
| Found the real brand | 92.5 % |
| Categorised | 88.8 % — the rest admit they don't know |
| Agrees with itself | 99.5 %, across 1,516 checks |
| Values with receipts | 26,596 |
| Products linked to each other | 60 % — 614 connections |
| Category rulebooks worked out | 64 |
| Official accuracy | 48.0 % — **on two rows** |
| Tests | 46 passing |
| Dependencies | 0 |

---

## Notes

- **Say "two rows" out loud and pause.** Admitting the weak number is the most
  convincing thing in the whole video. Don't soften it.
- Don't speed up the enrichment clip. The real four seconds is the flex.
- Cold Space? Stop. Let it wake. Never talk over a loading spinner.
- Upload **unlisted** to YouTube, or Drive set to **anyone with the link —
  Viewer**. Test it in a private window before you paste it anywhere.
