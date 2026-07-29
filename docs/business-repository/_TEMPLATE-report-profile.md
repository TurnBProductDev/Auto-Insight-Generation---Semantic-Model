# R0n — <Report Name>

<!--
HOW TO USE
1. Copy to reports/R0n-<slug>.md and fill in every section.
2. Add a row to the report index in README.md.
3. Delete guidance comments as you go. Leave no placeholder unanswered - write
   "[UNVERIFIED] - pending <owner>" rather than deleting a section you cannot yet fill.
4. Do NOT restate global standards. Record only DEVIATIONS, each with a business reason.
5. Tag every claim [VERIFIED] / [INFERRED] / [UNVERIFIED]. Never silently promote a tier.
-->

| Field | Value |
|---|---|
| **Report ID** | R0n |
| **Domain** | |
| **Primary fact table** | |
| **Reporting grain** | |
| **Business owner** | |
| **Technical owner** | |
| **Status** | Draft / Active / Deprecated |
| **Profile version** | 1.0 (YYYY-MM-DD) |

---

## 1. Purpose

<!-- What business questions does this report answer, and who acts on it? Two or three
     sentences. If you cannot name the decision it informs, question whether the report
     should exist. -->

---

## 2. Semantic model map

### 2.1 Tables

| Table | Role | Notes |
|---|---|---|
| | | |

### 2.2 Comparison pattern

<!-- CRITICAL: how does this model compute prior period? Options:
     - Physical prior-year columns on the fact row (R01's pattern - no time intelligence)
     - A proper date dimension with SAMEPERIODLASTYEAR / DATEADD
     - Snapshot tables per period
     Getting this wrong produces DAX that silently returns the wrong period. -->

### 2.3 Known column drift

<!-- Differences between the Desktop file and the published dataset. Distinguish a
     rename from a genuine structural difference - the latter breaks DAX outright.
     If none is known, say so, and re-check after any model republish. -->

| Concept | Desktop file | Published dataset |
|---|---|---|
| | | |

### 2.4 Key columns

| Column | Role | Status |
|---|---|---|
| | Entity key (comparable-population filter applies here) | |
| | Trading date - or state "none exists" | |
| | Finest validated time grain | |

---

## 3. Entity master

<!-- Every trading unit, classified. This drives the comparability doctrine and is the
     section most likely to go stale - a store opening or closing changes it. -->

| Entity | Classification | Prior-period history | Treatment |
|---|---|---|---|
| | Comparable / Current-only / Prior-only / Inactive | | |

**Comparable population:** <list>

<!-- For each excluded entity state WHY (opened when, closed when). A rule without a
     reason gets deleted by whoever inherits this file. -->

### 3.1 Configuration mirror

```json
"insight_comparable_population": [],
"insight_excluded_entities":     []
```

Must match section 3 exactly and change in the same commit.

### 3.2 Estate materiality

<!-- How many comparable entities? With few, a single one can drive a group figure and
     entity-level detail belongs in every group-level explanation. -->

---

## 4. KPI framework

| # | KPI | Bound measure | Direction | Red | Amber | Green |
|---|---|---|---|---|---|---|
| | | | | | | |

### 4.1 Threshold philosophy

<!-- Why these bands? Which KPIs carry the tightest bar and what commercial stance does
     that express? Thresholds without rationale get renegotiated arbitrarily. -->

### 4.2 Measure coverage notes

<!-- Which KPIs are materialised in the model vs computed by the KPI layer? Which are
     bound to no visual (invisible to dashboard readers)? Any measure with unsafe
     division or known quirks? -->

---

## 5. Latest measured position

Source: <artifact>, run <date>

| KPI | Value | Status |
|---|---|---|
| | | |

<!-- State caveats BEFORE interpretation: is it comparable-scoped? How stale? -->

### 5.1 Reconciliation

<!-- Do the identities from global standards 2.1 hold? Show the arithmetic. A break is a
     data-quality finding that outranks commercial interpretation. -->

### 5.2 Commercial reading

<!-- Expert interpretation. Cover:
     - Where growth actually came from (traffic / basket / price)
     - What is masking what
     - Composition risk: how durable is the headline if its main driver normalises?
     - Breadth: broad or concentrated?
     Name the readings the arithmetic CANNOT separate, and say what would separate them. -->

### 5.3 Known defects in these figures

<!-- Scoping errors, unfiltered measures, stale data. State DIRECTION and likely SIZE of
     any error, not just its existence. -->

---

## 6. Data quality register

<!-- One subsection per known issue. For each: what it is, how it manifests, what it
     rules out, and how the agent handles it. -->

### 6.1 <Issue>

---

## 7. Deviations from global standards

| Standard | Deviation | Reason |
|---|---|---|
| | | |

<!-- If none, say "No deviations." Explicitly. -->

---

## 8. Fiscal calendar

<!-- Fiscal year start month; whether current/prior follow fiscal or calendar year; any
     4-4-5 or retail-calendar convention; reporting timezone. Never assume January. -->

---

## 9. Open items

| # | Item | Type | Owner |
|---|---|---|---|
| 1 | | Governance / Commercial / Definition / Data quality / Capability | |

### On first live connection, verify

<!-- A concrete checklist someone can execute in one session. -->

---

## 10. Change log

| Date | Version | Change | Author |
|---|---|---|---|
| YYYY-MM-DD | 1.0 | Initial profile. | |
