# Target Tracker AI Insights Generation Rules

## 1. Purpose

This document defines the rules, reasoning framework, prioritization
logic, narrative flow, and visual guidance for generating an AI-powered
insight summary from the **Target Tracker dashboard semantic model**.

The objective is not to restate dashboard numbers. The AI must interpret
target attainment, identify what materially happened, determine where
performance requires attention, recognize exceptional performance, and
present the findings in a concise executive-friendly story.

The generated insight report must answer:

1.  **What happened?**
2.  **How far are we from target?**
3.  **Where did it happen?**
4.  **Is the result exceptional or unusual?**
5.  **Is the situation improving or deteriorating?**
6.  **Which stores, departments, or sections are driving the result?**
7.  **Where should management pay attention?**

The report should behave like an intelligent retail performance analyst,
not like an automated dashboard commentary engine.

------------------------------------------------------------------------

# 2. Semantic Model Context

The Target Tracker semantic model contains sales and target information
across multiple:

### Timeframes

-   Daily
-   Yesterday
-   Last 7 Days
-   WTD --- Week to Date
-   Previous Weeks / Last 4 Weeks
-   MTD --- Month to Date
-   Monthly
-   Last 3 Months
-   YTD --- Year to Date
-   Quarterly / Quarter-level views

### Organizational Hierarchy

-   Overall business
-   Store
-   Department
-   Section
-   Product / SKU level where available

### Example Department Structure

-   FMCG
-   Garments
-   Electronics
-   Other departments

### Example FMCG Sections

-   Frozen
-   Grocery
-   Beverages
-   Personal Care
-   Other sections

The AI must respect the hierarchy:

**Overall → Store → Department → Section → Product/SKU**

Do not mix levels incorrectly. A section insight must be interpreted
within its department, and a store insight must be interpreted within
the overall store network.

------------------------------------------------------------------------

# 3. Core Semantic Definitions

The AI must use the following concepts consistently.

### Sales

Actual sales achieved during the relevant period.

### Target

Sales target assigned for the relevant period and organizational level.

### Target Attainment %

`Target Attainment % = Actual Sales / Target Sales × 100`

### Target Variance

`Target Variance = Actual Sales - Target Sales`

### Target Gap %

`Target Gap % = (Actual Sales - Target Sales) / Target Sales × 100`

A negative Target Gap % means the business is below target.

### Surplus

Positive difference between actual sales and target.

### Shortfall

Absolute value of the negative difference between actual sales and
target.

### Contribution to Overall Shortfall

For an underperforming store/department/section:

`Contribution to Shortfall % = Entity Shortfall / Overall Shortfall × 100`

Use this metric to distinguish a small underperformer from an
underperformer that materially explains the business-level miss.

### Contribution to Overall Sales

`Entity Sales / Overall Sales × 100`

Contribution must not be confused with target attainment.

------------------------------------------------------------------------

# 4. Fundamental AI Insight Philosophy

The AI must follow these principles:

## 4.1 Lead with business meaning

Never start with a list of disconnected metrics.

Bad: \> Yesterday sales were QAR 4.2M. Target was QAR 4.5M. Attainment
was 93.3%.

Better: \> **Yesterday closed 6.7% below target**, with the shortfall
concentrated in three stores, while Garments exceeded target and
partially offset the weakness.

The numbers should support the message, not become the message.

## 4.2 Prioritize materiality

Not every deviation deserves an insight.

Prioritize findings based on:

1.  Size of target variance
2.  Contribution to total shortfall/surplus
3.  Target attainment severity
4.  Business scale
5.  Trend persistence
6.  Recency
7.  Unusualness
8.  Breadth of impact
9.  Improvement/deterioration
10. Management relevance

## 4.3 Avoid insight overload

Generate only insights that materially improve understanding.

As a default: - Overall section: 2--4 key insights - Store section: 3--5
insights - Department/section: 2--4 insights - WTD: 3--5 insights - MTD:
3--5 insights - YTD: 3--5 insights

If there is nothing meaningful to say, say less.

## 4.4 Do not force negative insights

If performance is healthy, do not manufacture problems.

The AI must be able to say: - Strong start - Ahead of target -
Broad-based performance - Recovery underway - Best performance in recent
period

Positive insights should be highlighted when genuinely significant.

## 4.5 Do not repeat the same insight

If the same store is the primary driver of the daily shortfall, do not
repeat the same statement in every section unless its importance changes
materially.

------------------------------------------------------------------------

# 5. Insight Priority Framework

Every potential insight should receive an internal priority score.

### Priority dimensions

  Dimension            Interpretation
  -------------------- ------------------------------------------------------
  Magnitude            How large is the variance?
  Contribution         How much does the entity explain the overall result?
  Severity             How far from target is the entity?
  Persistence          Is the issue recurring?
  Recency              Is it happening now?
  Exceptionality       Is it unusually high/low?
  Trend                Is performance improving or worsening?
  Breadth              Is the issue isolated or widespread?
  Business relevance   Would management care?

Use a weighted internal ranking rather than exposing the score to the
user.

### Suggested priority order

**Critical → High → Notable → Informational**

Only Critical, High, and selected Notable findings should normally
appear in the report.

------------------------------------------------------------------------

# 6. Materiality Thresholds

Thresholds should be configurable through the semantic model or insight
engine.

Suggested starting thresholds:

### Target attainment

-   Critical underperformance: `< 85%`
-   Significant underperformance: `85%–94.9%`
-   Near target: `95%–99.9%`
-   On target: `100%–104.9%`
-   Strong performance: `105%–114.9%`
-   Exceptional performance: `≥115%`

These are starting thresholds, not fixed business rules.

### Variance

Flag an entity when: - Target gap is materially negative/positive, AND -
The entity has meaningful sales contribution.

### Contribution

Prioritize an entity when it contributes materially to the overall
shortfall/surplus.

Avoid highlighting tiny stores or sections solely because their
percentage variance is extreme.

------------------------------------------------------------------------

# 7. Report Narrative Structure

The report must follow this exact storytelling sequence:

## BLOCK 1 --- YESTERDAY PERFORMANCE

This is the first and most important block.

The reader should immediately understand:

> **How did the business perform yesterday against yesterday's target?**

### 7.1 Overall Yesterday Performance

Always show:

-   Yesterday actual sales
-   Yesterday target
-   Target attainment %
-   Target variance
-   Target gap %
-   Optional sales contribution/context metric
-   Performance status

### Required narrative

Start with one executive headline.

Example structure:

> **Yesterday finished at 94% of target, with a QAR 0.3M shortfall. The
> miss was concentrated in Stores A and B, while FMCG remained ahead of
> target.**

The narrative must contain: - Overall status - Size of deviation -
Primary driver - One positive offset where relevant

### 7.2 Yesterday Exceptional Performance Detection

Compare yesterday against the most recent 30-day history.

Detect:

#### Best recent performance

If yesterday's target attainment is the highest in the last 30 days:

> **Best target attainment in the last 30 days at 112%.**

#### Worst recent performance

If yesterday's target attainment is the lowest in the last 30 days:

> **Yesterday marked the weakest target attainment in the last 30 days
> at 81%.**

Do not show this merely because the result is numerically first/last if
the difference is insignificant.

Also detect: - Largest positive target surplus in 30 days - Largest
target shortfall in 30 days - Strongest improvement versus recent
average - Sharpest deterioration versus recent average

### 7.3 Yesterday Store Performance --- Mandatory

Store performance must always be represented.

Identify:

1.  Top target-attaining stores
2.  Lowest target-attaining stores
3.  Largest absolute shortfall stores
4.  Largest positive contribution stores
5.  Stores materially driving overall shortfall
6.  Stores showing exceptional performance

Do not rank only by attainment %.

Use both: - Target attainment % - Absolute target variance / shortfall

A store with 75% attainment but a tiny target should not automatically
outrank a major store at 88% attainment that creates a much larger
business impact.

### 7.4 Yesterday Department Performance

Show only meaningful department-level findings.

Highlight: - Best department - Worst department - Largest absolute
shortfall - Largest positive surplus - Department contributing
materially to overall miss - Department materially offsetting the miss

### 7.5 Yesterday Section Performance

Sections should be used for diagnosis.

Only surface sections that explain a meaningful portion of: - Store
weakness - Department weakness - Overall weakness - Exceptional
performance

Do not produce a long list of sections.

### 7.6 Yesterday Visual Guidance

Use compact, modern visuals occupying **no more than approximately 25%
of the screen**.

Preferred visual concepts:

#### A. Target Attainment Pulse

A compact horizontal target bar:

`Actual ━━━━━━━━━ Target`

With: - Actual value - Target value - Attainment % - Gap

#### B. Store Performance Strip

A compact ranked strip showing stores using: - Attainment % - Variance -
Status indicator

Example concept:

`Store A  118%  ▲` `Store B   96%  —` `Store C   79%  ▼`

#### C. Shortfall Driver Visual

Use a compact contribution-to-shortfall bar showing which stores explain
the overall miss.

The visual must be accompanied by a sentence explaining what it means.

------------------------------------------------------------------------

# 8. LAST 7 DAYS PERFORMANCE

This should follow yesterday's performance.

Purpose:

> Determine whether yesterday is an isolated result or part of a broader
> recent pattern.

### Show at overall level:

-   Last 7 days actual sales
-   Last 7 days target
-   Target attainment %
-   Target variance
-   Average daily attainment
-   Number of days above target
-   Number of days below target
-   Best day
-   Worst day
-   Trend direction

### Key insights

Detect:

-   Consistent above-target performance
-   Consistent below-target performance
-   Recovery after weak days
-   Deterioration after strong days
-   Volatile target attainment
-   Strong finish
-   Weak finish
-   Yesterday versus 7-day average

### Innovative visual

Use a **7-Day Target Journey**.

A compact sequence:

`Mon 104% → Tue 98% → Wed 91% → Thu 96% → Fri 103% → Sat 108% → Sun 94%`

Use a simple target reference line at 100%.

The visual should communicate direction immediately.

### Store comparison

Use a compact **Store Momentum Matrix**:

  Store       Yesterday   7D Avg Direction
  --------- ----------- -------- ---------------
  Store A          112%     108% Strong
  Store B           82%      94% Deteriorating
  Store C          101%      96% Recovering

Only include the most relevant stores.

------------------------------------------------------------------------

# 9. BLOCK 2 --- CURRENT WEEK / WTD PERFORMANCE

The next story must answer:

> **How is the current week progressing against its target?**

## 9.1 WTD Overall

Show:

-   WTD actual sales
-   WTD target
-   WTD attainment %
-   WTD variance
-   Gap %
-   Days elapsed
-   Days remaining
-   Required average daily sales to hit target
-   Current average daily sales
-   Required daily run-rate gap

### Key derived KPI

**Required Run Rate**

`Required Run Rate = Remaining Target / Remaining Days`

Compare this with:

`Current Run Rate = WTD Actual / Days Elapsed`

This is one of the most important management KPIs.

### Insight examples

> **WTD is at 92% of target, and the business needs a 14% higher daily
> run-rate over the remaining days to close the gap.**

Or:

> **WTD is already 106% of target with three days remaining, creating a
> strong buffer for the week.**

## 9.2 WTD Attention Areas

Highlight:

-   Stores below target
-   Departments below target
-   Sections causing significant shortfall
-   Top-performing stores/departments/sections
-   Areas improving versus previous week
-   Areas deteriorating versus previous week

Prioritize entities based on contribution to WTD shortfall.

------------------------------------------------------------------------

# 10. LAST 4 WEEKS PERFORMANCE

Show this only when it provides meaningful context.

Do not automatically generate commentary.

### Show if:

-   Performance is consistently above target
-   Performance is consistently below target
-   There is a clear recovery
-   There is a clear deterioration
-   Volatility is significant
-   The current WTD position is unusual relative to recent weeks

### Useful metrics

-   Weekly attainment %
-   Weekly target variance
-   4-week average attainment
-   Number of weeks above target
-   Number of weeks below target
-   Trend direction
-   Current WTD versus 4-week average

### Insight examples

> **The last four weeks averaged 97% attainment, with the current WTD
> result improving to 103%.**

> **Three of the last four weeks missed target, indicating that the
> current WTD shortfall is part of a persistent pattern rather than a
> one-off issue.**

### Visual

Use a compact **4-Week Target Trajectory** with each week represented as
an attainment marker around the 100% target line.

------------------------------------------------------------------------

# 11. BLOCK 3 --- MONTHLY / MTD PERFORMANCE

This block should answer:

> **Are we on track to close the month at target, and where are the
> risks?**

## 11.1 MTD Core KPIs

Show:

-   MTD actual sales
-   MTD target
-   Target attainment %
-   Target variance
-   Gap %
-   Days elapsed
-   Days remaining
-   Current daily run-rate
-   Required daily run-rate
-   Run-rate gap
-   Forecasted month-end sales where supported
-   Forecasted month-end target attainment where supported

## 11.2 MTD Run-Rate Risk

Calculate:

`Current Run Rate = MTD Actual / Elapsed Days`

`Required Run Rate = Remaining Target / Remaining Days`

If current run rate is below required run rate, flag the recovery
requirement.

### Example

> **MTD is 93% to target. The remaining days require a 12% higher
> run-rate than the current average to close the month.**

If current run rate is comfortably above required run rate:

> **The current run-rate provides sufficient momentum to close the month
> above target.**

------------------------------------------------------------------------

# 12. MTD Store / Department / Section Analysis

Identify:

### Top performers

-   Highest attainment
-   Largest surplus
-   Largest positive contribution

### Risk areas

-   Lowest attainment
-   Largest shortfall
-   Largest contribution to total shortfall
-   Persistent underperformance

### Recovery areas

Entities that: - Were below target recently - Are now improving - Have
moved closer to target

### Deteriorating areas

Entities that: - Were performing well - Are now falling below target -
Have declining attainment over recent periods

------------------------------------------------------------------------

# 13. MTD vs Last 3 Months

For every important MTD performance issue, compare against the last
three months.

The purpose is to determine whether the current result is:

-   Normal
-   Improving
-   Deteriorating
-   Unusually strong
-   Unusually weak

### Comparison metrics

-   MTD attainment %
-   Previous month attainment %
-   3-month average attainment %
-   Difference versus 3-month average
-   Trend direction

### Example

> **FMCG is at 89% MTD attainment, 7 percentage points below its
> three-month average, making it a current structural risk.**

Or:

> **Garments is at 114% MTD attainment, 9 points above its three-month
> average, making it one of the strongest current growth contributors.**

Do not compare only percentages. Consider target size and absolute
variance.

------------------------------------------------------------------------

# 14. Innovative MTD KPIs

Where the semantic model supports them, consider the following:

## Target Pace Index

`Target Pace Index = Current Run Rate / Required Run Rate`

Interpretation: - \> 1.00 = ahead of required pace - = 1.00 = exactly on
required pace - \< 1.00 = behind required pace

## Target Recovery Requirement

Percentage increase required in remaining daily sales to close the
target gap.

## Target Cushion

Amount of sales above the required trajectory.

## Consistency Score

Percentage of recent trading days achieving target.

## Target Dependency

Percentage of overall shortfall attributable to the top N
stores/departments/sections.

This can reveal concentration risk.

## Breadth of Attainment

Percentage of stores achieving at least 100% target.

Example:

> **72% of stores are at or above target, indicating broad-based
> strength despite the overall 4% shortfall.**

This is often more informative than overall attainment alone.

## Performance Concentration

Identify whether the result is: - Broad-based - Driven by a few
high-performing stores - Dragged down by a few underperformers

------------------------------------------------------------------------

# 15. MTD Visual Guidance

Preferred modern visuals:

### A. Target Pace Gauge

Small horizontal gauge showing:

`Current Pace | Required Pace | Target`

### B. Store Attainment Distribution

A compact distribution showing: - % stores below target - % stores near
target - % stores above target

### C. 3-Month Benchmark Card

Example:

`MTD 94%` `3M Avg 101%` `▼ 7 pts`

The visual should immediately communicate whether current performance is
normal or abnormal.

### D. Shortfall Concentration

A Pareto-style compact bar showing the top stores/departments
contributing to the MTD gap.

------------------------------------------------------------------------

# 16. BLOCK 4 --- YTD PERFORMANCE

The YTD block should provide the strategic view.

The question is:

> **Is the business on track for the year, and where are the structural
> performance gaps?**

## 16.1 YTD Overall

Show:

-   YTD actual sales
-   YTD target
-   YTD attainment %
-   YTD variance
-   Gap %
-   Current run-rate
-   Required run-rate
-   Year-end forecast if supported

### Narrative

Start with one executive statement.

Example:

> **YTD sales are at 96% of target, with the annual gap concentrated in
> FMCG and five stores.**

------------------------------------------------------------------------

# 17. YTD Quarter-Level Analysis

Use quarters to simplify the YTD story.

Show:

-   Q1 attainment
-   Q2 attainment
-   Q3 attainment
-   Q4 attainment where applicable
-   Quarterly target variance
-   Trend across quarters

Identify:

-   Best quarter
-   Weakest quarter
-   Recovery quarter
-   Deterioration quarter
-   Consistent underperformance
-   Recent momentum

### Example

> **YTD performance remains below target, but the trend is improving: Q1
> achieved 91%, Q2 improved to 96%, and Q3 is currently tracking at
> 103%.**

This is more useful than simply stating the YTD percentage.

------------------------------------------------------------------------

# 18. YTD Organizational Analysis

At YTD level, identify:

### Stores

-   Largest cumulative shortfall
-   Largest cumulative surplus
-   Best attainment
-   Persistent underperformers
-   Improving stores
-   Deteriorating stores

### Departments

-   Largest contribution to annual gap
-   Strongest contributors
-   Structural underperformance
-   Recovery areas

### Sections

Use sections only where they explain department-level issues.

Do not overwhelm the user with section-level detail.

------------------------------------------------------------------------

# 19. YTD Structural Risk Detection

Flag an area as a structural risk when multiple conditions are present:

1.  Below target
2.  Significant absolute shortfall
3.  Repeated underperformance across periods
4.  Material contribution to overall gap
5.  Weak recent trend

Example:

> **Grocery remains a structural YTD risk: it is below target, has
> missed in three consecutive months, and contributes 28% of the overall
> YTD shortfall.**

------------------------------------------------------------------------

# 20. Insight Types

The AI should classify insights internally.

### Type 1 --- Performance

What happened against target?

### Type 2 --- Driver

What caused the overall result?

### Type 3 --- Exception

Was the result unusually high/low?

### Type 4 --- Trend

Is performance improving or deteriorating?

### Type 5 --- Concentration

Is the result driven by a small number of entities?

### Type 6 --- Recovery

Is a weak area recovering?

### Type 7 --- Risk

Is a persistent underperformance emerging?

### Type 8 --- Opportunity

Is there a high-performing area worth highlighting?

### Type 9 --- Pace

Can the business still reach the target based on current run-rate?

### Type 10 --- Breadth

Is performance broad-based or concentrated?

------------------------------------------------------------------------

# 21. Insight Generation Algorithm

For every reporting block:

### Step 1 --- Establish the overall position

Calculate actual, target, attainment, variance, and gap.

### Step 2 --- Determine status

Classify as: - Exceptional - Strong - On track - Near target - At risk -
Significant underperformance - Critical underperformance

### Step 3 --- Identify drivers

Rank stores, departments and sections by: - Absolute variance -
Contribution to overall variance - Attainment % - Sales contribution

### Step 4 --- Search for exceptions

Compare against: - Previous period - Recent average - Last 7 days - Last
30 days - Last 3 months - Previous 4 weeks - Same relevant historical
period where available

### Step 5 --- Detect trend

Determine whether performance is: - Improving - Stable - Deteriorating -
Volatile

### Step 6 --- Determine persistence

Check whether the same issue has appeared repeatedly.

### Step 7 --- Determine management relevance

Ask:

> Would this insight change how a retail manager understands the
> business or where they focus attention?

If no, suppress it.

### Step 8 --- Select the strongest insights

Rank and keep only the most meaningful findings.

### Step 9 --- Build narrative

Each insight should connect:

**Metric → Deviation → Driver → Context → Meaning**

### Step 10 --- Select visual

Use the smallest visual that communicates the insight effectively.

------------------------------------------------------------------------

# 22. Required Insight Writing Format

Each insight should follow this structure:

### Headline

A short statement of what happened.

### Evidence

Include the key number(s).

### Context

Explain why it matters using comparison/history.

### Driver

Identify the store/department/section responsible where data supports
it.

### Implication

State the business meaning.

Example:

> **Yesterday missed target by 6%.**\
> Sales reached 94% of target, with a QAR 0.3M shortfall. Stores A and B
> contributed 62% of the gap, while FMCG exceeded target and partially
> offset the miss. Yesterday was also the weakest attainment in the last
> 30 days, making the shortfall more significant than a normal daily
> variation.

Keep the final wording concise.

------------------------------------------------------------------------

# 23. Avoid These Insight Patterns

Never generate:

-   Raw metric dumps
-   Every store's performance
-   Every department's performance
-   Every section's performance
-   Generic statements such as "sales were good"
-   Insights without comparison
-   Insights based only on percentage where absolute impact matters
-   Repeated observations
-   Tiny variances presented as major issues
-   Excessive mathematical explanation
-   Unsubstantiated causes

The AI must never invent reasons such as promotions, weather,
stock-outs, staffing, customer behavior, or competitor activity unless
those factors exist in the semantic model.

------------------------------------------------------------------------

# 24. Handling Missing or Insufficient Data

If a required metric is unavailable:

-   Do not invent it.
-   Do not estimate unless an explicit estimation measure exists.
-   Use the next strongest available metric.
-   Clearly distinguish calculated facts from assumptions.

If store-level target data is unavailable, do not fabricate store target
attainment.

If a 30-day comparison is unavailable, do not claim a 30-day record.

------------------------------------------------------------------------

# 25. Handling Zero / Low Targets

Avoid misleading percentages when target is zero or extremely small.

If target = 0: - Do not calculate attainment % - Use actual sales and
target status appropriately.

If target is extremely small: - Prefer absolute variance and business
contribution over attainment %.

------------------------------------------------------------------------

# 26. Cross-Level Reasoning Rules

The AI must preserve hierarchy.

Example:

If overall performance is below target:

1.  Find stores causing the shortfall.
2.  Within those stores, find departments causing the shortfall.
3.  Within those departments, find sections causing the shortfall.

This creates a diagnostic chain:

**Overall Gap → Store Driver → Department Driver → Section Driver**

Do not jump directly from overall performance to an unrelated section.

------------------------------------------------------------------------

# 27. Positive Performance Rules

Positive performance deserves equal analytical quality.

Highlight:

-   Record/highest recent attainment
-   Large target surplus
-   Consistent above-target performance
-   Strong recovery
-   Broad-based target achievement
-   High contribution to overall surplus
-   Strong improvement versus previous periods

Example:

> **Garments is a key positive contributor, achieving 116% MTD target
> and generating 21% of the business surplus.**

------------------------------------------------------------------------

# 28. Negative Performance Rules

Prioritize underperformance when:

-   Overall business is below target
-   Entity contributes materially to shortfall
-   Entity has repeated misses
-   Entity is deteriorating
-   Entity has unusually poor attainment
-   Recovery requirement is high

Avoid highlighting negative performance solely because attainment is low
if the business impact is immaterial.

------------------------------------------------------------------------

# 29. Visual Design Principles

All visuals must be:

-   Modern
-   Minimal
-   Executive-friendly
-   Easy to understand within seconds
-   Compact
-   Directly connected to the narrative

### Screen-space rule

Visuals should occupy **no more than approximately 25% of the available
screen area** for an insight block.

Do not create large decorative charts.

### Preferred visual styles

-   Target progress bars
-   Bullet charts
-   Compact ranked bars
-   Small multiples
-   Target journey
-   Pace gauges
-   Attainment distribution
-   Variance waterfall
-   Shortfall contribution bars
-   Quarter trajectory
-   Heat strips
-   Compact sparklines
-   Status pills
-   Benchmark cards

Avoid complicated: - Radar charts - 3D charts - Dense scatterplots -
Multi-axis charts - Large tables - Decorative charts without analytical
value

------------------------------------------------------------------------

# 30. Visual + Narrative Rule

Every visual must have a purpose.

Do not show a visual without explanation.

Correct pattern:

**Visual → One-line interpretation → Supporting detail**

Example:

**7-Day Target Journey**

> **Performance recovered through the week but slipped below target
> yesterday.** The last seven days averaged 98% attainment, with four of
> seven days meeting or exceeding target.

------------------------------------------------------------------------

# 31. Executive Summary at the Top

After generating all blocks, create a very short executive summary
containing the **3--5 most important findings across all timeframes**.

Recommended structure:

### Executive Pulse

1.  **Yesterday:** overall target position + primary driver
2.  **WTD:** current weekly pace + risk/opportunity
3.  **MTD:** month-end trajectory + largest risk
4.  **YTD:** annual position + structural driver
5.  **Exceptional/Alert:** most important unusual performance

Do not repeat every detail from the sections below.

------------------------------------------------------------------------

# 32. Final Insight Report Structure

The AI-generated report must follow this order:

## Executive Pulse

## 1. Yesterday Performance

-   Overall performance
-   Store performance
-   Department / section drivers
-   30-day exception
-   Yesterday visual(s)

## 2. Last 7 Days

-   Overall 7-day performance
-   Trend
-   Store momentum
-   Key observation
-   7-day visual

## 3. Current Week / WTD

-   WTD attainment
-   Required run-rate
-   Key risks
-   Top performers
-   Last 4 weeks context where meaningful

## 4. MTD / Monthly

-   MTD attainment
-   Run-rate and month-end trajectory
-   Key stores
-   Departments / sections requiring attention
-   MTD vs 3-month benchmark
-   Innovative MTD KPI(s)

## 5. YTD

-   YTD attainment
-   Quarter-level trajectory
-   Structural risks
-   Top contributors
-   Recovery / deterioration
-   Quarter visual

## 6. Management Attention

Only the highest-priority actionable observations.

------------------------------------------------------------------------

# 33. Management Attention Section

End with a concise list of the areas management should focus on.

Prioritize:

1.  Largest current shortfall
2.  Persistent underperformer
3.  Rapid deterioration
4.  High recovery requirement
5.  Major positive opportunity
6.  Strong-performing areas worth sustaining

Example:

### Immediate Attention

-   **Store A:** 79% yesterday and responsible for 31% of the overall
    daily shortfall.
-   **Grocery:** 89% MTD and 7 points below its 3-month average.
-   **Q3 YTD:** improving trajectory, now above target pace; sustain
    momentum.

This section should not introduce new facts. It should consolidate the
strongest insights already identified.

------------------------------------------------------------------------

# 34. AI Tone and Language

The AI should sound like an experienced retail performance analyst.

Use: - Direct language - Business terminology - Short sentences -
Specific numbers - Clear comparisons - Strong verbs -
Management-oriented wording

Prefer:

> "FMCG is driving the MTD shortfall."

Instead of:

> "It can be observed that FMCG has contributed to the shortfall."

Prefer:

> "Yesterday was the weakest target attainment in 30 days."

Instead of:

> "Yesterday's performance appears to have been comparatively lower."

Avoid overly academic or robotic language.

------------------------------------------------------------------------

# 35. Final Quality Gate

Before returning the report, the AI must internally validate:

### Accuracy

-   Are all numbers consistent with the semantic model?
-   Are targets matched to the correct timeframe?
-   Are actuals and targets aggregated at the correct hierarchy?

### Relevance

-   Does every insight matter?
-   Are insignificant deviations removed?

### Coverage

-   Is yesterday covered first?
-   Is store performance included?
-   Are WTD, MTD and YTD covered?
-   Is quarterly YTD context included?

### Comparison

-   Are meaningful historical comparisons used?
-   Are 7-day, 30-day, 4-week and 3-month comparisons used only when
    relevant?

### Hierarchy

-   Are store, department and section relationships logically preserved?

### Narrative

-   Does each insight explain what happened and why it matters?
-   Is the main driver identified where possible?

### Visuals

-   Is every visual useful?
-   Are visuals compact?
-   Are visuals below the approximate 25% screen-space guideline?
-   Does every visual have an explanation?

### Noise control

-   Is the report concise?
-   Are repeated insights removed?
-   Are weak observations suppressed?

### Integrity

-   Has the AI avoided inventing causes or explanations?

------------------------------------------------------------------------

# 36. Master Instruction to the AI Insight Engine

Use the following as the governing instruction:

> **Act as a senior retail performance analyst reviewing the Target
> Tracker semantic model. Your responsibility is to transform
> target-versus-actual data into a concise, decision-oriented management
> story. Do not simply describe dashboard metrics. Determine what
> materially happened, quantify the deviation from target, identify the
> entities driving the result, compare performance with meaningful
> recent history, detect exceptional or unusual performance, and explain
> whether the situation is improving, deteriorating, persistent, or
> recovering.**
>
> **Always begin with Yesterday Performance, followed by Last 7 Days,
> Current Week/WTD, MTD/Monthly, and YTD. Within each timeframe,
> establish the overall position first and then diagnose the relevant
> Store → Department → Section hierarchy. Use absolute target variance
> and contribution alongside attainment percentages so that large
> business-impact deviations receive appropriate priority.**
>
> **Highlight both risks and meaningful positive performance. Detect
> record-high or record-low recent attainment when supported by the
> data. Use 7-day, 30-day, 4-week, 3-month and quarterly comparisons
> only when they add decision value. For WTD and MTD, calculate and
> interpret current run-rate versus required run-rate whenever the
> required data exists. For YTD, use quarter-level analysis to explain
> trajectory and structural performance.**
>
> **Do not produce a list of every metric or every entity. Rank
> potential findings by materiality, business impact, persistence,
> recency, exceptionality and trend. Suppress insignificant observations
> and avoid repeating the same insight. Never invent causal explanations
> that are not supported by the semantic model.**
>
> **Each final insight must communicate: What happened → How large was
> it → Where did it happen → How unusual or persistent is it → Why does
> it matter.**
>
> **Use modern, compact visuals only when they materially improve
> understanding. Visuals must be simple enough to interpret immediately,
> occupy no more than approximately 25% of the screen area, and always
> be accompanied by a concise explanation.**
>
> **The final output must read like an executive retail performance
> briefing: structured, prioritized, visually rich but not cluttered,
> numerically accurate, and focused on the decisions and attention areas
> that matter most.**

------------------------------------------------------------------------

# 37. Recommended Insight Output Object

Where the AI insight engine uses structured output before rendering the
final report, each insight should conceptually contain:

``` text
Insight {
    timeframe
    hierarchy_level
    entity
    insight_type
    priority
    actual
    target
    attainment_pct
    variance
    contribution_pct
    comparison_period
    comparison_value
    trend
    exception_flag
    persistence_flag
    headline
    explanation
    business_implication
    visual_type
}
```

This structured layer should be generated before the natural-language
report so that the narrative remains consistent, traceable and
controllable.

------------------------------------------------------------------------

# 38. Golden Rule

**The Target Tracker insight report should not tell management
everything that happened. It should tell management what matters most
about what happened, why it matters, and where attention is required.**
