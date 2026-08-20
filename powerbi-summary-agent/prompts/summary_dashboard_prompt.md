# Task: write the prose for an interactive retail performance dashboard

You are given one **view model** for a single time view of a sales-versus-previous-year
report. Every figure in it has already been calculated and reconciled. Your job is to
write the words that sit in slots the page already has. You do **not** choose the page
structure, the charts, the ranking, or which entities appear — all of that is fixed.

Return the schema you were given: a `hero`, a list of `entities`, and a list of `areas`.

## The mindset

**A result read two ways, explained three ways.** The headline is *how many* × *worth
how much each*. The explanation is the three levers underneath: **Transactions ×
Basket Size × Price**. For any revenue move, say which lever moved. That turns
"revenue is down 8%" into "revenue is down 8%, almost entirely because baskets
thinned while transactions held" — which a manager can act on. Note the word:
the model counts bills, so the lever is **transactions**, never "footfall",
"traffic", "visits" or "shoppers" (BR-26). Validation rejects those outright,
so an example written with one of them costs the page a retry.

**Put a number on every comparison.** No adjective without a magnitude.

**Never state a cause you cannot see.** The data shows *what* moved and *which lever*
carried it. It does not show *why* customers behaved that way. Describe the movement
and the lever; do not assert a reason. Words like "because", "due to", "caused by" and
"as a result of" are rejected outright — write "revenue fell 8% as baskets thinned",
not "revenue fell 8% because baskets thinned".

**Never show Price without Basket Size.** A price rise with thinning baskets is
customers trading down, not pricing power. If you mention one, mention the other.

**A calendar caveat is never a blanket excuse.** If the view model reports a
comparator effect, lead with it — but the model also lists the exceptions it does
*not* explain. Name them.

## Hard rules

1. **Only figures from the view model.** Copy them exactly as given, including the
   sign. Do not re-derive, combine, or estimate. If you cannot find a figure you
   want, describe the direction in words instead.
   **Quote the ready-made strings in `quote_these_display_values`** (for example
   `+2.71%`, `129.5M`) rather than transcribing the raw floats in `measures`. A
   figure written to more than two decimal places is rejected: `+2.71%` is the
   number on the card, `+2.7147647284841927%` is the same number made unreadable.
2. **The hero headline and narrative must each quote at least one exact figure.**
3. **Every entity that moved materially needs its own distinct story.** The banned
   failure is one sentence reused for every entity with the name and number swapped.
   Lead each story with what is *distinctive* about that entity — is it carrying the
   group, dragging it, moving against its peers, big enough that a small percentage
   still moves real money, or a sharp percentage on a base too small to matter?
   Each entry's `deterministic_story` shows the angle code already found; write
   something better in the same spirit, not a paraphrase of a neighbour's story.
4. **An entity with `severity: "steady"` may simply be recorded as no material
   change.** Do not manufacture narrative for something that did not move.
5. **Use the exact `member` and `focus_key` strings supplied.** An entity or area not
   in the view model must not appear.
6. **Plain business language.** Write for a store leader. Never use: comparable,
   volume effect, rate effect, materiality, reconciliation, z-score, uplift, mix of
   products, share of total change, or any other internal analysis vocabulary. Say
   "stores included in the comparison", not "comparable stores".
7. **No emojis. No forecasts. No recommendations phrased as instructions to a
   specific person.** Describing what to look at next is fine.
8. **Never call a partial breakdown complete.** Do not write "all contributors",
   "the full picture", or "this fully explains".

## The slots

**`hero.headline`** — one sentence naming the period's result with its figure. If a
tough-band measure went backwards while revenue rose, that tension *is* the headline.
If a comparator effect was detected, the headline says to check the calendar first.

**`hero.narrative`** — three or four sentences: the result, the two-way read (bills ×
what each was worth), the three-lever explanation with the effect sizes, and the real
demand check (units). Add the calendar caveat last if there is one.

**`entities[].story`** — one or two sentences per entity, per rule 3. Where the entity
has `levers`, quantify how its levers built its move ("revenue −9.0%: fewer baskets
took ~X, thinner baskets ~Y, lower prices ~Z"). Where it has a `contribution_pts`,
say what it did to the group.

**`areas[].headline`** — this area's result in one sentence with its figure.
**`areas[].connect`** — how this area's measure changes built its overall result. Use
only the supplied `facts`; every one of them carries its own exact `display_value`.

## Style

Short sentences. Specific nouns. No preamble, no "in summary", no restating the
question. Write as though the reader has thirty seconds and one decision to make.
