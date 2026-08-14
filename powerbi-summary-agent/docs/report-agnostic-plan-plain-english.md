# Making the agent handle any report — the plan in plain English

**Who this is for:** anyone who needs to understand or approve this work without reading code.
**The technical version:** `report-agnostic-execution-plan.md` — same plan, written for the
developer who will build it.
**One-line summary:** today the agent can only answer one question. This plan lets you give
it new questions by filling in a form instead of writing code.

---

## 1. What the agent does today

Every day, without anyone touching it, the agent:

1. Logs into Power BI on its own.
2. Reads the dashboard's structure — what measures and columns exist, how they connect.
3. Works out for itself which numbers to fetch, and writes the database queries.
4. Fetches the numbers.
5. Decides what is worth talking about, and what is noise.
6. Writes two reports: one saying **what** the numbers are, one saying **why** they look
   that way.
7. Checks its own writing — every figure it quotes must be a real figure it fetched.
8. Publishes both, and remembers what it said so tomorrow does not repeat today.

Nobody writes a query. Nobody writes the report. That part genuinely works, and it works
against a live model today.

---

## 2. The problem, in one paragraph

The agent can only ever answer **one** question: *"how does this period compare with the
same period last year?"*

That is not a wording choice we could change in a prompt. It is built into the agent's
foundations. The smallest thing the agent understands is **a change between two periods**.
Everything above that — deciding what matters, ranking areas, choosing what to write about,
writing it — is defined in terms of that change. Remove the change and the agent has
nothing to think with.

**An analogy.** Imagine a set of kitchen scales that has been designed so deeply around
weighing that the concept of "heavier or lighter than yesterday" is stamped into every part
of it. It weighs beautifully. But if you ask it how *long* something is, it cannot give you
a smaller or rougher answer — it has no idea what you are talking about.

That is where we are. Ask for a stock report and there is no "last year" — there is only
*"how much is on the shelf right now, and is that too much or too little?"* That is a
**different kind of question**, not a harder version of the same one.

### How we know this for certain

Three pieces of evidence:

- The phrase "last year's figure" appears in the code **about 330 times**, across 30 of the
  40-odd modules. Not as wording — as arithmetic. The function that works out how big a
  movement is *literally is* "this year minus last year". Take last year away and it
  returns nothing.
- The ranking that decides what leads the report needs a percentage change to exist. With
  no last year, every single area comes back labelled *"not comparable"* — the report would
  be a page of blanks.
- **The agent already tells you this itself.** Point it at a stock dashboard today and it
  refuses, with this message:

  > *"This dashboard has no measures that compare one period with the same period a year
  > earlier, and that comparison is the whole basis of what this agent reports. […] A stock
  > or inventory snapshot with only current balances cannot be used."*

  That message is honest and correct. It is also exactly the wall this plan removes.

---

## 3. The good news: most of the work is already reusable

Underneath the "last year" assumption, the machinery is in good shape and does not care
what kind of report it is serving.

| Already reusable, whatever the report | What it does |
|---|---|
| Logging in and staying logged in | Handles Power BI security, no browser prompt |
| Reading the dashboard's structure | Finds measures, columns, how tables connect |
| Writing safe database queries | Knows the traps this database has and avoids them |
| Checking a query before running it | Catches a query naming something that does not exist |
| Staying inside budget | Caps how many queries a run may make, caches repeats |
| Making the parts add up | Refuses to publish a percentage that does not reconcile |
| Ranking sensibly | Stops a £300 movement leading the report at "+2,166%" |
| Not repeating itself | Remembers what it said, rotates topics fairly |
| Checking its own writing | Every quoted figure must exist; no invented numbers |
| Building the web page | One self-contained file, charts, search, print |
| Publishing | Three destinations, and it knows when one failed |
| The setup wizard | Connect → check the model → configure → validate → deploy |

**So this is not a rebuild.** It is taking four decisions that are currently bolted into
the walls and writing them down on a card instead.

**A better analogy than the scales.** Think of a professional kitchen. The ovens, the
knives, the fridge, the hygiene rules, the staff training — all of that works for any
cuisine. What is currently hard-coded is *the recipe*, and right now the recipe has been
built into the walls. We are going to write it on a card.

---

## 4. The fix: a report definition card

For each report, someone fills in a **report definition** — a form covering eight things.
The agent reads the card and works out how to behave.

| # | The card asks | Today's answer (the retail sales report) |
|---|---|---|
| 1 | **What is this report for?** Who reads it, what do they decide, what is out of scope | Regional managers deciding on range and branch action |
| 2 | **What are we comparing against?** The yardstick | The same period last year |
| 3 | **What are we measuring?** Each number, what it means, which direction is good | Revenue, units, transactions |
| 4 | **How is the business split up?** The levels and groupings | Division → Department → Section → Category, plus branches |
| 5 | **How do we explain a change?** The formulas | Revenue = transactions × basket size × price |
| 6 | **What counts as worth mentioning?** Thresholds and what to ignore | 10% movement, 5% of the business |
| 7 | **How should the page read?** Layout, tone, banned wording | The four-part dashboard; say "transactions", never "footfall" |
| 8 | **Where is the written background?** The rulebook | `business_rules.md` |

Everything on that card is a **setting**. Nothing on it is code.

---

## 5. The most important item on the card: the yardstick

"What are we comparing against?" is the single most consequential answer, because it
changes what every other number on the page *means*. Six kinds cover the retail reports
we can foresee:

| The yardstick | What "movement" means | Example report |
|---|---|---|
| **The same time last year** | This year minus last year | Sales vs last year *(today's report)* |
| **A target or budget** | Ahead of or behind plan | Sales vs budget, labour vs plan |
| **A rule about how much we should hold** | How far outside the agreed range we are | Stock health, out-of-stock risk |
| **The last snapshot we took** | Up or down since last week | Stock movement week on week |
| **A promised standard** | How many **points** off the promise | Supplier fill rate, on-time delivery |
| **Nothing — the mix is the point** | How the shares shifted between areas | Category mix, channel mix |

Each yardstick is a small, self-contained piece of code — about a page each. Once one
exists, you can create **unlimited reports of that kind** by filling in cards, with no
further code.

### Why "points" gets its own row

A supplier fill rate going from 92% to 88% has dropped **4 points**. It has *not* dropped
"4.3%". Both sentences sound fine; only one is true, and the wrong one will get repeated in
a meeting. Writing "this is measured in points" on the card makes that a guarantee the
machine enforces, rather than an instruction we hope the AI remembers.

---

## 6. The one that trips everyone up: stock

This is worth understanding properly, because it is the reason stock reporting is a real
piece of work and not a form-filling exercise.

**Money adds up over time. Stock does not.**

- Sell £100 a day for 30 days → you made **£3,000**. Adding it up is right.
- Hold 100 units on the shelf every day for 30 days → you have **100 units**, not 3,000.
  Adding it up is nonsense.

Right now the agent cannot tell those two kinds of number apart. It treats every number as
the money kind. Point it at a stock measure and it will report a figure **thirty times too
big**, and — this is the dangerous part — every one of its internal "do the parts add up?"
checks will pass, because it will have summed both the parts and the whole the same wrong
way. It would be confidently, invisibly wrong.

So stock reporting needs three things built before any card can be filled in:

1. **Teach the agent the difference** between numbers that add up over time and numbers
   that do not — and make it *prove* which kind each measure is by testing it against the
   real data, rather than trusting what the card says.
2. **A new way of ranking.** Today's ranking needs a percentage change. A stock report has
   none. It needs "how far outside the rules is this, how much money is tied up in it, and
   how long has it been like this?"
3. **A new way of remembering.** Today the agent remembers "I already reported October's
   drop". A stock report needs "this SKU has been below its reorder point for **9 days**" —
   so it does not re-announce the same problem as brand new every morning, but does speak up
   when the problem gets worse or clears.

None of that is configuration. It is roughly six weeks of real work, and it is honest to
say so up front.

---

## 7. What people configure vs what stays in the code

This distinction is the whole point of the exercise.

### You configure — no developer needed

- What the report is for, who reads it, what it must not be used for
- Which yardstick to compare against, and what to call it in plain words
- Which numbers to report, what each means, which direction is good, and how they behave
- Which levels and groupings the business is split into
- Which levels get their own written story, and which just get a ranked table row
- The formulas used to explain a change
- What counts as big enough to mention, and what to ignore
- How often a topic may repeat
- The page layout and section order
- Approved and banned wording
- The written rulebook

### The code owns — the same for every report, forever

- Logging in and handling security
- Reading the dashboard's structure
- Writing and checking database queries, and the traps it must avoid
- Staying inside the query budget
- Making the parts add up, and **refusing to publish figures that do not**
- The ranking mathematics
- Remembering what has been said, and writing memory safely
- Checking its own writing — every quoted figure must be real
- Building the web page
- Publishing, and reporting honestly when publishing fails
- Never inventing a number, never forecasting, never claiming a cause it cannot prove

### And to be straight about it — when code *is* still needed

| What you want | Code needed? |
|---|---|
| A new number, level, threshold, layout choice, or wording rule | **No** |
| A whole new report using a yardstick that already exists | **No** |
| A new formula using a shape we already support | **No** |
| A brand new kind of yardstick | **Yes** — about a page of code |
| A new way of ranking | **Yes** — one function |
| A new chart type | **Yes** — one function |
| A new kind of page section | **Yes** — two small functions |

Each of those is a small, contained, testable addition. The promise is *"no code for each
new report"* — not *"no code ever"*.

---

## 8. Where information should live: three homes

Right now everything is jumbled into one 827-line document that mixes three completely
different kinds of fact. They need separating, because they change at different speeds and
have different readers.

| Home | Holds | Read by | Changes when |
|---|---|---|---|
| **Company settings** | Which dashboard, where files go, currency, VAT, timezone | The machine | The company changes |
| **The report card** | Yardstick, numbers, levels, thresholds, layout | The machine, which **enforces** it | The report's policy changes |
| **The report rulebook** | What things mean, why we decided them, how to interpret, what never to say | The AI, which **respects** it | The business changes its mind |

**The rule of thumb:** if a computer can check it, it is a setting. If it needs explaining,
it goes in the rulebook.

An example of the pair working together:

- **Setting:** exclude branch CFH022 from the comparison. *The machine enforces this — the
  branch physically cannot appear in a like-for-like figure.*
- **Rulebook:** *"CFH022 opened in March 2025, so it has no last-year baseline. It is still
  counted in total sales. Decided by Finance, March 2025. Revisit March 2026."* *The AI reads
  this so it can explain itself, and a human reads it to know whether it is still true.*

Today both of those facts sit in the same markdown file, and only the explanation half is
actually enforced.

### A standard shape for every rulebook

Every report gets a rulebook from the same template, so anyone can find anything:

1. Rules at a glance (a summary table)
2. What this report answers
3. What this report must **not** be used for
4. What each number means — one block per number
5. The yardstick, and why it is a fair one
6. Who is left out, and why — one block per exclusion
7. Calculation rules (the numbered ones)
8. How to interpret what we see
9. The thresholds, and why those numbers
10. Approved and banned words, with reasons
11. Known data problems we have accepted
12. Open assumptions someone still needs to confirm

Every rule keeps a mark saying how much we trust it: **checked against live data**,
**a business decision**, or **an assumption someone needs to confirm**. That habit already
exists in the current rulebook and is worth keeping — it is what stops a guess quietly
hardening into a fact.

---

## 9. Setting up a new report: the journey

**Once per client** (mostly what already exists today):

1. Connect — which dashboard, which AI service
2. Where files go — the three storage destinations
3. Company facts — currency, VAT, timezone, financial calendar

**Then, per report** — this is the new part:

4. **Pick a report type** from a gallery of starting points
5. Purpose and scope — the question, the audience, what is out of scope
6. **Check the dashboard** — see section 10
7. The yardstick, and who is included
8. The numbers — match each dashboard measure to a number the report uses
9. The levels — which get a story, which get a table row
10. The formulas *(optional)*
11. What counts as worth mentioning
12. How the page should read
13. Write the rulebook
14. Validate, then publish

That looks like a lot, but **picking a report type in step 4 fills in most of steps 7–12
automatically.** In practice a new report is around **15 questions** — the same design goal
the current wizard already hits.

### Starting points we would ship

| Starting point | For |
|---|---|
| Sales vs last year | Today's report |
| Actual vs budget | Any plan or target comparison |
| Stock health | Inventory against policy |
| Service level | Availability, fill rate, on-time delivery |
| Supplier performance | Procurement scorecards |
| Mix and composition | Category or channel share shifts |
| Blank | For experts who want to declare everything by hand |

A starting point only fills the form in. Once saved, the report stands on its own — so you
can always see exactly what produced a given report, which is how the agent works today
and should keep working.

---

## 10. Why "check the dashboard" is a gate, not a step

Several questions genuinely cannot be answered before looking at the real data: which
levels exist, whether branch names can be identified, whether there is a real business date
(as opposed to a date stamped on when the data was loaded), whether the parts add up.

Guessing any of those does not produce an error. It quietly produces a wrong report. So the
wizard runs a **check** against the live dashboard first. It costs nothing to publish
because it writes nothing, uses no AI, and touches no live files.

The check reports back:

- **Numbers** — did we find each one? Is it the kind of number the card says it is?
  (Including the "does it add up over time?" test from section 6.)
- **Levels** — how many members does each have, and **do the parts add up to the whole?**
- **Who is included** — how many are in, out, new, or dormant
- **Dates** — is there a real business date, how fresh is it, is the latest period finished?
- **Formulas** — do the declared formulas actually balance on real numbers?
- **Blocking problems** — plain-English stops, e.g. *"Your card says fill rate is a
  percentage, but the measure it points at adds up to 4,712 across branches, which a
  percentage cannot do. Either the card is wrong or the measure is."*

Some findings are **hard stops** — the setup will not let you publish. The most important:
a level whose parts do not add up to the whole. That would publish wrong percentages, and
it would do it quietly. Better to refuse.

One new screen is worth calling out: a **threshold tester**. It replays the numbers already
fetched by the check through your chosen thresholds and shows you **exactly which areas
would have been reported**. That is the only honest way to set a threshold, and it costs
nothing extra to run.

---

## 11. Adding a brand new report, start to finish

```
 1  Create      Pick a starting point. Most of the form fills itself in.
 2  Describe    Answer the ~15 questions that remain. Nothing has touched
                the dashboard yet, so this costs nothing.
 3  Check       Run the dashboard check. Get recommendations and blocking problems.
 4  Fix         Apply recommendations with one click. Re-check. Use the
                threshold tester to see what would actually get reported.
 5  Write       Fill in the rulebook from the template. The tool tells you
                which sections are still empty.
 6  Preview     See the real page, built from the check's own numbers.
                No live run, no AI, nothing published. Catch layout problems cheaply.
 7  Validate    Blocking problems must all be clear.
 8  Dry run     A full real run, AI and all, but published nowhere. Then an
                automatic audit re-checks every promise the card makes.
 9  Publish     Deploy the settings and the rulebook.
10  Runs daily  No code was written at any point.
```

**The test of whether this whole programme succeeded:** step 10 works for a report type
nobody anticipated, and no code file changed.

---

## 12. Timeline, and what you will see

| Stage | How long | What you will see |
|---|---|---|
| **1. Build the safety net** | 1–2 weeks | **Nothing.** Automated checks that prove the existing reports have not changed by a single character |
| **2. Move the recipe onto a card** | 3–4 weeks | **Nothing.** Same reports, same output, now driven by a card |
| **3. Turn the lists into settings** | 3–4 weeks | **Nothing.** Numbers and levels become editable rather than fixed |
| **4. First new yardstick — vs budget** | 2–3 weeks | **The first new report type.** Proves the design works |
| **5. Stock reports** | 4–6 weeks | Stock health reporting. The hard one — see section 6 |
| **6. Many reports per client** | 2 weeks | More than one report from one dashboard |
| **7. The new setup screens** | 4–6 weeks | Non-developers can configure a report start to finish |
| **8. Layouts and wording as settings** | 3 weeks | Page structure becomes editable |
| **9. Move the live report across** | 2 weeks | The current report runs on the new foundation |
| **Then** | ongoing | Service level, supplier, mix — **configuration only, no code** |

**Total: roughly 6 to 8 months** for one developer working on this properly.

### The uncomfortable bit, stated plainly

**Stages 1, 2 and 3 produce nothing you can see, and they are about 40% of the effort.**

That will feel like three months of nothing. It is not. The agent's real asset is that its
numbers are trustworthy — it has already caught and fixed several bugs where figures
looked perfectly reasonable and were wrong (contributions adding up to −38 points against
a −52% move; a wrong branch contaminating a prior-year total). Those fixes are invisible
and easy to undo by accident.

Stage 1 builds an automated check that compares every new version against the current
reports, character by character, and fails if anything moved. Stages 2 and 3 then make
large structural changes *behind* that check. Skip stage 1 and those hard-won correctness
fixes will come undone silently, and nobody will notice until a manager acts on a wrong
number.

**Recommendation:** do not let stages 1–3 be cut or reordered.

---

## 13. Four reports, side by side

Here is how four genuinely different retail reports would be set up. Notice how much stays
the same.

### What is different on each card

| | Sales vs last year | Stock health | Sales vs budget | Supplier performance |
|---|---|---|---|---|
| **Question it answers** | How are we trading vs last year? | Where is stock outside policy, and how much money is at risk? | Which areas are behind plan? | Which suppliers are hurting us? |
| **Yardstick** | Same period last year | The agreed stock range | The approved budget | The promised service standard |
| **Movement means** | Up or down in £ | How far outside the range | Ahead of or behind plan | How many **points** off |
| **Main numbers** | Revenue, units, transactions | Units on hand, weeks of cover, value tied up | Revenue vs budget, % of plan | Fill rate, on-time %, lead time |
| **Split by** | Merchandise levels + branches | Product + warehouse | Merchandise levels + branches | **Supplier** |
| **Ranked by** | Impact, size, unusualness | How bad, how much money, how long | Size of the gap, % of plan | Points off, order volume |
| **Page shape** | Four-part dashboard | A prioritised problem list | A scorecard grid | A supplier scorecard |
| **Remembers** | "Already reported October" | "Below reorder point, day 9" | "Already reported the gap" | "Already reported the drop" |
| **Holiday-shift check** | On | Off | Off | Off |

### What is identical on all four

| | |
|---|---|
| Logging in and staying logged in | ✔ all four |
| Reading the dashboard's structure | ✔ all four |
| Writing and checking safe queries | ✔ all four |
| Staying inside the query budget | ✔ all four |
| Making the parts add up — and refusing to publish if they do not | ✔ all four |
| Sensible ranking that ignores freak percentages on tiny numbers | ✔ all four |
| Not repeating yesterday's story | ✔ all four |
| Checking its own writing; never inventing a figure | ✔ all four |
| Building the web page | ✔ all four |
| Publishing to three places, honestly reporting failures | ✔ all four |
| The whole setup journey | ✔ all four |
| The automatic audit of the finished report | ✔ all four |

**That second table is the return on the investment.** Twelve capabilities, built once,
serving every report we will ever write.

---

## 14. Things that could go wrong

Six honest risks, and what we do about each.

**1. Three months with nothing to show.**
Stages 1–3 are invisible. Someone will ask why we are not shipping.
→ *Say so up front, and point at the safety-net check as the deliverable. See section 12.*

**2. Stock reporting gets promised too early.**
"It's just configuration now" will be said before it is true.
→ *Stock needs three real capabilities built first (section 6). It is stage 5, not stage 4.*

**3. Someone fills the card in wrong.**
Say the wrong kind of number and the report is confidently wrong.
→ *The check does not trust the card. It tests each number against real data and refuses to
publish when the two disagree.*

**4. The AI gets more ways to word a number badly.**
More report types means more chances to describe a figure wrongly.
→ *The wording rules are assembled from checks that already exist and are already tested.
And the agent's plain, no-AI backup version of every report is itself tested to pass the
strict wording checks — so the checks can never leave it with nothing to publish.*

**5. Report quality slips in a way no automated check catches.**
Numbers can be right and the writing still poor.
→ *A human reads one real report per new report type. This is a named step, not optional.*

**6. Two ways to configure things during the transition.**
Old settings and new cards will coexist for a while.
→ *Old settings keep working untouched — the card is worked out automatically from them.
A fixed removal date, and the safety net checks both paths until we switch over.*

---

## 15. If you remember five things

1. **The agent is not "configured for" last-year comparisons — it is built out of them.**
   That is why this is real engineering and not a settings change.
2. **But most of the machine is reusable.** Twelve major capabilities do not care what kind
   of report they serve. We are moving the recipe out of the walls and onto a card.
3. **Stock is the hard one**, because money adds up over time and stock does not — and the
   agent currently cannot tell the difference. That is stage 5, about six weeks.
4. **The first three stages show you nothing** and are 40% of the work. They are what stops
   correct numbers quietly becoming wrong ones. Do not cut them.
5. **The finish line:** somebody who has never seen the code configures a report type
   nobody anticipated, and it starts running daily. No code was written.
