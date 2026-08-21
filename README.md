# CALIPER

**Evidence-bound product intelligence for industrial commerce.**
*Measured, not guessed.*

Built for **UniHack** — Unilog's AI-Powered Product Intelligence challenge.

---

## The problem, stated honestly

A distributor hands over a row like this:

```
Mfg_Part_Num : 49-94-1940
Part_Desc    : 49-94-1940 Milw 14"x1/8"x1" Masonry Cut Off Disc
E1_Brand     : -- Unbranded --
DIB_Brand    : -- No DIB Brand --
Part_Manuf   : Milwaukee Accessory (4031)
```

Unilog's delivery format expects **252 columns** out the other side: an approved
brand with the right ® symbol, a classpath, five separate descriptions written
to five different length and casing rules, and an ordered list of attributes
drawn from a controlled vocabulary.

Most solutions to this feed the row to an LLM and hope. CALIPER does not let the
model near an output cell.

---

## The core idea: facts before prose

Everything the pipeline learns about a product goes into a **Product Fact
Graph** — typed, evidenced claims:

```
brand       = Milwaukee®        registry match   conf 0.94   ev: "Milwaukee Accessory (4031)"
item_type   = Cut Off Disc      rule ITM-LEX-01  conf 0.91   ev: "Cut Off Disc"
diameter    = 14 in             rule DIM-CHN-02  conf 0.92   ev: chars 5-18  `14"x1/8"x1"`
thickness   = 1/8 in            rule DIM-CHN-02  conf 0.92   ev: chars 5-18  `14"x1/8"x1"`
arbor_size  = 1 in              rule DIM-CHN-02  conf 0.92   ev: chars 5-18  `14"x1/8"x1"`
application = Masonry           llm  LLM-EXT-01  conf 0.80   ev: "Masonry"
```

Rules, the brand registry, taxonomy, family consensus and the LLM **all write
facts**. Composition, validation and export **only read them**. That one-way
boundary is the entire design, and three things fall out of it:

- **No ungrounded value can reach a cell.** A `Fact` without `Evidence` is
  rejected at insertion. The model's proposals are discarded unless the quoted
  substring is actually present in the source.
- **The five descriptions cannot contradict each other.** They are five
  renderings of one fact set, not five independent generations.
- **Provenance is free.** Every populated cell ships with the rule that made it
  and the characters that justified it — 27,255 of them on the sample catalogue.

---

## Quick start

No pip install. No API key. Python 3.9+.

```bash
python -m caliper run data/input/sample_1000_items.csv -o data/out
```

1,000 rows in ~5 seconds, producing:

| File | What it is |
|---|---|
| `delivery.csv` / `delivery.xlsx` | The 252-column delivery format, header byte-identical to the published sheet |
| `audit_provenance.csv` | One row per populated cell: value, method, confidence, rule id, evidence span |
| `review_queue.csv` | Rows needing a human, ranked by value of review |
| `relationships.csv` | The product relationship graph — 589 evidence-backed edges |
| `corrections.csv` | Reviewer decisions and how many rows each one fixed |
| `report.json` | Every metric below |

Then open the console:

```bash
python -m caliper serve
```

### Two ways to run it

Open `python -m caliper serve` and the first screen asks how to run:

| Mode | What it does |
|---|---|
| **Deterministic only** | Rules, registries and induced specs. No network, no key, fully reproducible. ~2 s for 1,000 rows. |
| **Deterministic + AI** | Everything above, plus a model on the rows rules could not resolve, and an optional second-opinion audit. Needs your own key. |

Pick a provider (Groq, Gemini, Anthropic, OpenAI), paste a key, upload a file.
The key is held in the server process's memory for the session only — never
written to disk, never logged, and never returned to the browser.

### The model as auditor, not author

Extraction asks a model to produce values, which is where hallucination enters.
`--audit` inverts it: the deterministic engines produce the facts, and the model
only renders a verdict on facts that **already exist**.

```
SUPPORTED    the source text supports this value
UNSUPPORTED  the source cannot support it
UNKNOWN      the source is silent; no opinion
```

A verdict cannot create a value, so the audit pass has no path to inventing
anything. What it can do is disagree — and disagreement is the useful signal:

- a fact the rules produced **and** an independent model confirms has two
  methods behind it, and its confidence rises by *agreement* rather than by a
  constant attached to a rule;
- a fact the model rejects keeps its value but loses confidence and is routed to
  review, because a value two independent methods disagree about is exactly what
  a steward should look at.

```bash
python -m caliper run <input.csv> --llm groq --audit -o data/out
```

### Turning the AI layer on

```bash
cp .env.example .env      # then paste a key into .env
python -m caliper run data/input/sample_1000_items.csv --llm groq -o data/out
```

Any one of `GROQ_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
is picked up automatically. Model ids are **auto-detected** from the provider's
`/models` endpoint rather than hard-coded, because model names rot.

Responses are cached to `data/cache/llm/` and that cache is committed — so the
AI-enriched run reproduces byte-for-byte **with no key and no network**.

### When the AI quota runs out

Free tiers have daily caps — Groq's is 200,000 tokens per day, and it is not
reported in the rate-limit headers, so it can only be discovered by hitting it.
CALIPER handles that in three places:

1. **Before the run.** The key is probed at setup. A rejected key, or a quota
   already spent, is reported immediately with the reset time and a one-click
   *"Continue without AI"*.
2. **During the run.** A `429` naming a *per-day* limit trips a circuit breaker.
   Per-minute limits are worth waiting out; per-day limits are not, because
   nothing in this run will clear them. Further calls short-circuit instantly
   instead of retrying into a wall, and the run finishes deterministically.
3. **After the run.** The report carries `ai_degraded`, and the overview shows
   how many rows got a model pass before the budget ran out.

All 252 columns are produced either way. The model never writes an output cell,
so losing it costs coverage on hard rows — not correctness on easy ones.

### Tests

```bash
python tests/test_core.py     # 42 invariant checks, standard library only
```

They test the promises the design makes — an unevidenced value cannot enter the
graph, the invoice line is compliant by construction, an audit verdict can never
create a value — rather than numbers that move as rules improve.

### Other commands

```bash
python -m caliper learn-spec <labelled.csv>          # derive a category pack
python -m caliper eval "" --truth <labelled.csv>     # score against ground truth

# record a reviewer decision that replays on every future run
python -m caliper correct --scope family --target F-8ecfff1c     --key item_type --value "Sanding Sheet" --by mohit
python -m caliper correct --list
```

### It is not built for one file

The brief requires a prototype *"capable of processing the evaluation test
dataset"* — so the pipeline must not be wired to the sample's headers. A
deliberately hostile test file ships in `data/input/foreign_schema_test.csv`:
different column names, different order, and two junk columns.

```
Vendor Name | internal_id | MFR PART # | Item Description | Make | notes | qty_on_hand
```

```bash
python -m caliper run data/input/foreign_schema_test.csv -o data/out_foreign
```

```
schema : mpn=MFR PART #, description=Item Description, brand=Make,
         manufacturer=Vendor Name, sku=internal_id
brand resolved 95.0% · classified 95.0% · INVOICE_DESC 100%
```

Roles are detected by name, then by content sniffing for anything still
unclaimed; `notes` and `qty_on_hand` are correctly ignored. The same detection
runs on files dropped into the console.

---

## Results on the published sample

1,000 rows, deterministic core plus the gated LLM layer:

| | |
|---|---|
| Throughput | 1,000 rows in 5.3 s (deterministic), no API key required |
| Brand resolved to an approved name | **91.0 %** |
| Classified to a classpath | **88.8 %** — the remainder abstain rather than guess |
| `INVOICE_DESC` ≤ 40 chars, upper case | **100 %** |
| `SHORT_DESC` within limit | **100 %** |
| `MOBILE_DESC` in the 60–80 window | 65.7 % — the remaining 34.3 % are data-limited, 0.0 % composition faults |
| Rows invoking the LLM | **22 %** — the rest are resolved by rules |
| Product families found | 566 from 1,000 rows |
| Facts inherited by family consensus | 77 |
| Relationship edges derived | **589** — 61 % of products connected |
| Source-data defects flagged | 4 brand/manufacturer mismatches, 2 family anomalies |
| Reviewer-correction leverage | 1 decision → 6 rows (family-scoped) |

Against the published ground truth (**2 labelled rows** — sample size stated
everywhere, because two rows is a narrow base):

| Field | Exact |
|---|---|
| `BRAND_NAME` (with ® symbol) | 100 % |
| `Classpath`, `Dept`, `Class`, `Fine` | 100 % |
| `Product Name` | 100 % |
| `MANUFACTURER_PART_NUMBER` | 100 % |
| `ATTRIBUTE_LABEL 1–15` | 100 % |
| **In-scope fields overall** | **48.0 %** exact, 0.51 token-F1 |

`ATTRIBUTE_LABEL` accuracy comes from a category pack learned from those same
two rows. That is *given structure*, not prediction, and the evaluation report
labels it as such.

---

## Three findings from the data

These came out of measurement, and each one changed the build.

### 1. The answer key fills 25 % of the sheet. Over-filling is a defect.

```
ground-truth row 1 : 63 / 252 columns  (25.0 %)
ground-truth row 2 : 71 / 252 columns  (28.2 %)
blank in both      : 173 columns
```

The 173 blanks include `UPC`, `EAN`, `GTIN`, `UNSPSC`, `List Price`, every
dimension, `WEIGHT`, `SDS`, `Warranty Information` and `Country Of Origin`.
**Unilog's own analysts leave them empty.** A pipeline that fills 90 % of the
sheet is inventing roughly two-thirds of a catalogue. CALIPER calibrates its
fill rate against the answer key and reports the comparison on the dashboard.

### 2. Attribute *values* are not recoverable from the supplier row.

The input for the labelled dishwasher is 39 characters:

```
PDSH4816AF Dishwasher SS - Display Only
```

The answer key for that row carries Voltage 120 V, Amperage 15 A, Sound Level
47 dBA, 5 Wash Cycles, Leg Mounting, Size 24 in W x 24-1/4 in D, Depth With Door
Open 50-1/4 in, and a Minimum Height of *"8-1/2 in Upper Rack, 11-1/4 in Lower
Rack"*.

**Eleven of the twelve populated attribute values appear nowhere in the input.**
Only `SS → Stainless Steel` is derivable.

So attribute values require the manufacturer's own source. Any pipeline
reporting high attribute-value accuracy from the input alone is overfitting to
the sample or fabricating — and the guide is explicit that a fluent description
built from invented values scores zero. CALIPER leaves them empty and flags the
gap rather than filling it with something plausible.

### 3. A guardrail caught a bug in our own parser.

The physical checks flagged four rows where the arbor hole was wider than the
wheel it is cut in — impossible. The cause was ours:

```
49-94-0058 Milw 12"x1/8"x20mm Metal Cut Off Disc
                              ^^^^ read as 20 INCHES
```

The dimension regex recognised `"`, `in` and `'` but not metric marks, so a
20 mm arbor became a 20 in arbor on a 12 in disc. Fixing the parser cleared the
relational finding; the domain finding then persisted, which turned out to be a
false positive in the *guardrail* — its range was stated in inches and never
converted. With both fixed, findings went **4 → 2 → 0**, and both defects were
real.

That is the loop working: the checks are independent enough of the extractors
to catch them being wrong.

### 4. The 1,000 rows are 566 families, not 180.

An early estimate put family amortisation at 8×. Measured, it is **1.77×**, with
378 singletons. That killed the cost argument, so family clustering was
repurposed to what it is actually good for: **corroborated consensus** (a value
propagates only when ≥2 siblings independently produced it and none disagree)
and **anomaly detection** (a sibling breaking a strong family pattern is usually
a defect in the source catalogue).

---

## Pipeline

```
 raw row
   │
 1 schema detection        any column naming; placeholders voided
 2 family clustering       566 families; membership carries confidence
 3 deterministic parse     dimension chains, grit, voltage, wattage, colour
                           temperature, pack counts, gauge, platform …
 4 identity resolution     "Phillips Lighting (5831)" → Philips®
                           distributor/co-op detection · mismatch flagging
 5 item type               induced vocabulary + attribute-co-occurrence inference
 6 taxonomy                Dept › Class › Fine › Classpath, abstains when unsure
 7 LLM extraction          only on rows rules could not reach (22 %);
                           evidence firewall discards unquoted values
 8 reviewer corrections    persisted human decisions, scoped and replayed
 9 physical guardrails     domain ranges, unit kinds, dimensional coherence
10 family consensus        corroborated propagation + anomaly detection
   │
 ── PRODUCT FACT GRAPH ──   everything above writes; nothing below writes
   │
11 composition             252 columns rendered; character-budget solver
12 relationship graph      powers / fits / variant_of / cross_reference
13 validation              guideline-as-code, each violation cites a rule id
14 selective delivery      ready / needs_review / blocked
```

### The character-budget solver

`INVOICE_DESC` has a hard 40-character ceiling in upper case. Asking a model to
"keep it under 40 characters" fails silently and often. Here it is a budget
problem: facts are ordered by how much they identify the product, each carries
an abbreviation ladder (`Stainless Steel → STAINLESS → SST → SS`), and the
solver fits as many as the budget allows — shortening before dropping, dropping
before overflowing.

```
CUT OFF DISC 14IN 1/8IN 1IN MASONRY      37/40   kept 5 facts
```

Compliance is guaranteed by construction, and the solver reports what it gave
up. **100 % on the sample catalogue.**

### Category-spec induction

A Unilog category specification — which attributes apply, in what order, with
what permitted values — is normally written by hand, one category at a time,
across tens of thousands of categories. CALIPER derives one from the rows
themselves, with a count behind every claim:

```
Electrical>Lighting & Bulbs>Light Bulbs     111 rows · 6 attributes
  Wattage 91% · Color Temperature 87% · Base Type 78% · Pack Quantity 57% …
```

Where a labelled file exists, `learn-spec` reads the positional slot order
straight out of it **and aligns each label to the fact key that reproduces its
value** — so a labelled category the pipeline has never seen produces a working
spec automatically.

### Short is not always wrong

`MOBILE_DESC` must land in a 60-80 character window, and 34.3 % of rows fall
short. That number is useless on its own, so the pipeline splits it:

```
in window                : 65.7 %
short, data-limited      : 34.3 %   every available fact is already in the line
short, composition fault :  0.0 %   facts left unused -- the only fixable part
```

A row like `GE Appliances GE®, Dishwasher, PDT715SYVFS, Stainless Steel` is
59 characters with nothing left to add. Reaching 60 would mean inventing
something. The two failure modes are counted separately because only one of
them is a bug, and an earlier build padded the gap with taxonomy nodes to make
the metric look better.

### Physical guardrails

Character validation catches a description that is too long. It does not catch
an arbor hole wider than its wheel, a 500 W LED lamp, or a "colour temperature"
that is really a part number. Guardrails reason about the *values*: domain
ranges, unit kinds, and relational coherence (`arbor_size < diameter`, converted
across units before comparison). A guardrail never edits a value — it lowers the
confidence and routes the row to review, because silently "fixing" an uncertain
number is how bad data gets laundered into a catalogue.

### Relationship graph

A flat 252-column sheet cannot say that this battery powers that ratchet. From
facts already extracted, CALIPER derives **589 edges** across 61 % of the
catalogue — every one carrying a rule id, a confidence and the shared evidence
that licenses it:

| Relation | Edges | Licensed by |
|---|---|---|
| `variant_of` | 370 | same product family |
| `same_series` | 195 | same brand and collection |
| `powers` | 18 | same brand and battery platform |
| `cross_reference` | 6 | same item type and dimensions, different manufacturer |
| `fits` | **0** | shared arbor size, or shared lamp base |

`fits` is implemented and tested but fires zero times on this catalogue, and
that is reported rather than hidden. The relation needs an arbor size on the
*tool* as well as on the wheel, and a lamp base on the *fixture* as well as on
the bulb — neither appears in these descriptions. An earlier build reported 840
`fits` edges; they were bulb-fits-bulb, because the luminaire pattern matched
the word "light" inside "Light Bulb". No edge is written because two products
"seem related" — with nothing to point at, nothing is asserted.

### Corrections that compound

A review queue that ranks work but forgets the answer makes a steward solve the
same problem every run. Corrections are stored as durable scoped facts and
replayed:

- `part` — one part number
- `family` — every sibling in a product family
- `classpath` — every product in a category
- `brand` — teaches the registry a supplier alias, fixing every future row from
  that supplier

One family-scoped decision in the sample fixes 6 rows and re-drives
classification. The largest family holds 65. Corrections enter through the same
door as everything else — as facts whose evidence names the person who decided —
so a human call is exactly as auditable as a rule.

---

## The console

```bash
python -m caliper serve
```

A dense operator console, not a marketing dashboard — hairline rules, tabular
numerals, `F1`–`F6` pane switching, `↑↓`/`Enter` row navigation.

- **Board** — throughput, resolution, disposition, character-limit compliance,
  fill rate against the answer key, and the defects found in the source data
- **Catalog** — every row; click one for its full evidence chain, cell by cell
- **Specs** — the induced category rulebooks, with fill rates and facet flags
- **Families** — clusters, members, and flagged anomalies
- **Queue** — review ranked by *uncertainty × sibling SKUs affected*, so the top
  item is the best use of the next human minute
- **Graph** — the relationship edges, filterable by relation, each with its
  rationale
- **Load** — drop in any CSV; column roles are detected, not assumed

---

## Design decisions worth defending

**Abstention over guessing.** 16.6 % of rows are left unclassified. A wrong
classpath silently invalidates every attribute validated against it, so the
pipeline says "I don't know" and routes the row to review.

**No third-party packages.** CSV *and* XLSX are read and written with the
standard library — XLSX is a zip of XML. Judges run this once, on their machine;
a `pandas`/`openpyxl` dependency is a needless way to fail.

**The LLM is an upgrade, not a dependency.** With no key the deterministic
engines still produce all 252 columns. With a key, 22 % of rows get a second
pass. The cache makes the AI run reproducible without either.

**Report the gaps.** The pipeline raises findings against the *source* data —
4 brand/manufacturer mismatches, 2 family anomalies, 52 unresolvable brands.
The guide calls noticing these a strength; the dashboard shows them on the front
page.

---

## Honest limitations

- **Two labelled rows.** Every accuracy figure rests on a calibration set of
  two. The harness prints the sample size beside every rate and scales
  untouched to a larger labelled file.
- **No manufacturer-source retrieval yet.** Finding 2 shows this is the binding
  constraint on attribute-value accuracy — not a missing rule.
- **No official controlled vocabularies.** The LOV, the 27,000-row
  manufacturer/brand master and the UOM standards are described in the guide but
  not distributed. The brand registry here is a ~75-entry bootstrap; LOV
  coverage is measured against CALIPER's *induced* vocabulary and labelled as
  such. All loaders accept the real files if they appear.
- **The long tail abstains.** 153 distinct item types in the tail classify
  poorly. Hand-coding them would be overfitting to the sample, which the brief
  explicitly warns against.

---

## Layout

```
caliper/
  schema.py          252-column contract, role detection, placeholder handling
  pipeline.py        stage orchestration, family consensus, validation
  core/
    facts.py         Fact, Evidence, ProductFactGraph — the one-way boundary
    parse.py         deterministic extraction with character spans
    identity.py      brand/manufacturer resolution, mismatch detection
    taxonomy.py      Dept›Class›Fine›Classpath with abstention
    induce.py        category-spec induction from raw rows
    packs.py         positional specs learned from labelled rows
    guardrails.py    physical and logical value checks
    knowledge.py     product relationship graph
    corrections.py   persisted reviewer decisions
    compose.py       five description formats, character-budget solver
  io/tabular.py      stdlib CSV + XLSX read/write
  llm/provider.py    provider-neutral adapter, model detection, disk cache
  eval/harness.py    field accuracy, char compliance, LOV coverage
  web/               the console
```
