""""As at a date" is not "over a period", and a date column will not say which.

Filtering a snapshot with a date *range* produces a confidently wrong number:
sum stock across every day in a month and you get roughly thirty times the stock
you hold. The reverse is just as bad - filtering a transaction table to "the
latest date" reports one day's trade as the month.

So the correct filter depends on what the column *is*, and the name does not
tell you. On the live models (WP0, 2026-08-13) the discriminator turned out to be
mechanical and clean:

    UPDATED_ON        1 distinct value      <- the as-of stamp
    doc_date1purch    180 distinct values   <- a purchase document date
    DOC_DATE2         165 distinct values
    DOC_DATE3       1,443 distinct values

An as-of stamp is shared by every row of a load. An event date varies per row.
That is a ratio, and ratios survive renaming - which name-matching does not, as
the sales model already showed when `LOC_CODE` matched no entity pattern.

The trap this must also avoid
-----------------------------
`REP_SSR_SAG[sortdate]` has 14 distinct values, is typed Date, and is **not** a
snapshot - it is the batch purchase period, i.e. the *age axis*. A rule that
said "few distinct values means snapshot" would misread it and start filtering
the ageing report to its newest batch. So fewness alone is not enough: a
retained snapshot history must also apply uniformly, and the pure judgement here
reports UNKNOWN rather than guessing when the evidence is ambiguous.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

#: Above this many distinct values a date column is an event stream. At or below
#: it - but above one - the evidence is ambiguous and is reported as such; see
#: the note in :func:`judge_date_role` for why a ratio test is not enough.
SNAPSHOT_MAX_DISTINCT = 60

#: Retained only so an existing caller can pass it; the ratio is no longer used
#: to classify, because it cannot separate a snapshot history from a grouped
#: axis. Kept as a reported diagnostic.
SNAPSHOT_MAX_DISTINCT_RATIO = 0.001

#: A single bucket holding more than this share of the primary metric means a
#: load/posting date, not business activity. Mirrors the existing
#: `insight_temporal_batch_share` test, which is how `UPDATED_DATE` was caught
#: on the sales model.
BATCH_CONCENTRATION_SHARE = 0.40


class DateRole(Enum):
    """What a date column actually is, and therefore how it must be filtered."""

    #: An as-of stamp. Correct filter: the latest value only.
    SNAPSHOT = "snapshot"
    #: A business event. Correct filter: a range.
    EVENT = "event"
    #: A data load or posting stamp. Not business activity at all.
    BATCH_LOAD = "batch_load"
    #: Not enough evidence. Reported, never guessed past.
    UNKNOWN = "unknown"

    @property
    def filter_style(self) -> str:
        return {
            DateRole.SNAPSHOT: "latest value only",
            DateRole.EVENT: "a date range",
            DateRole.BATCH_LOAD: "not usable as a business axis",
            DateRole.UNKNOWN: "undetermined - do not filter on it",
        }[self]


@dataclass(frozen=True)
class DateVerdict:
    column: str
    role: DateRole
    reason: str
    distinct_count: int = 0
    row_count: int = 0
    latest: Any = None
    detail: dict = field(default_factory=dict)

    @property
    def is_snapshot(self) -> bool:
        return self.role is DateRole.SNAPSHOT

    @property
    def usable_as_time_axis(self) -> bool:
        """Only a genuine event axis supports period-over-period reporting."""
        return self.role is DateRole.EVENT

    def summary(self) -> str:
        return (f"{self.column}: {self.role.value} "
                f"({self.distinct_count} distinct of {self.row_count} rows) - "
                f"{self.reason}")


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def judge_date_role(column: str,
                    *,
                    distinct_count: int,
                    row_count: int,
                    latest: Any = None,
                    bucket_shares: Sequence[Any] = (),
                    max_distinct: int = SNAPSHOT_MAX_DISTINCT,
                    max_distinct_ratio: float = SNAPSHOT_MAX_DISTINCT_RATIO,
                    batch_share: float = BATCH_CONCENTRATION_SHARE) -> DateVerdict:
    """Judge one date column from observations. Pure - no IO, no model.

    ``bucket_shares`` is each date bucket's share of the primary metric, when it
    has been measured. It is what separates a load date from a business date,
    and it is optional because the cardinality test alone already settles the
    single-snapshot case decisively.
    """
    distinct_count = int(distinct_count or 0)
    row_count = int(row_count or 0)
    base = {"column": column, "distinct_count": distinct_count,
            "row_count": row_count, "latest": latest}

    if distinct_count <= 0 or row_count <= 0:
        return DateVerdict(**base, role=DateRole.UNKNOWN,
                           reason="no rows or no values were observed")

    # A single value shared by every row is an as-of stamp, and nothing else
    # looks like this. Both live inventory facts land here.
    if distinct_count == 1:
        return DateVerdict(**base, role=DateRole.SNAPSHOT,
                           reason="every row carries the same date, so it stamps "
                                  "the load rather than varying per row")

    shares = [s for s in (_num(x) for x in bucket_shares) if s is not None]
    if shares and max(shares) >= batch_share:
        return DateVerdict(
            **base, role=DateRole.BATCH_LOAD,
            reason=f"one date holds {max(shares) * 100:.0f}% of the measure, which "
                   f"is a posting or load date rather than business activity",
            detail={"peak_share": max(shares)})

    ratio = distinct_count / row_count
    if distinct_count <= max_distinct:
        # A LOW COUNT IS NOT ENOUGH, and this was got wrong once against real
        # data: `REP_SSR_SAG[sortdate]` holds 14 purchase periods across 158,446
        # rows - a ratio of 0.00009 - and a "few distinct values means snapshot"
        # rule classified the ageing report's own age axis as an as-of stamp.
        # The ratio is tiny for ANY low-cardinality column in a large table, so
        # it cannot separate "one stamp per load" from "fourteen groups".
        #
        # Only `distinct == 1` is decisive from cardinality alone. Anything else
        # in this range is genuinely ambiguous and is reported as such. What
        # would settle it is whether each date repeats the FULL member set (a
        # retained snapshot history) or partitions it (a grouped axis) - that
        # needs a second query, so it is named here rather than guessed at.
        return DateVerdict(
            **base, role=DateRole.UNKNOWN,
            reason=f"{distinct_count} distinct dates across {row_count:,} rows - "
                   f"too few to be an event stream, too many to be a single "
                   f"as-at stamp. This is either a retained snapshot history or "
                   f"a grouped axis such as a purchase period; telling them "
                   f"apart needs checking whether every date repeats the same "
                   f"members",
            detail={"distinct_ratio": ratio, "ambiguous": True})

    return DateVerdict(
        **base, role=DateRole.EVENT,
        reason=f"{distinct_count} distinct dates varying per row, which is a "
               f"business event stream",
        detail={"distinct_ratio": ratio})


def pick_snapshot_column(verdicts: Sequence[DateVerdict]) -> DateVerdict | None:
    """The as-of stamp, when exactly one column qualifies.

    With more than one, the most concentrated wins - fewest distinct values -
    because that is the one stamping the load. Ties return None rather than
    picking arbitrarily: filtering on the wrong stamp is the failure this
    module exists to prevent.
    """
    snapshots = [v for v in verdicts if v.is_snapshot]
    if not snapshots:
        return None
    if len(snapshots) == 1:
        return snapshots[0]
    snapshots.sort(key=lambda v: (v.distinct_count, v.column))
    if snapshots[0].distinct_count == snapshots[1].distinct_count:
        return None
    return snapshots[0]


# --- DAX ---------------------------------------------------------------------

def latest_snapshot_var(column_ref: str, var_name: str = "__latest_snapshot") -> str:
    """A VAR pinning the newest snapshot, ignoring any inbound date filter.

    `REMOVEFILTERS` on the date column only - never on the table - so a
    population filter applied elsewhere survives. Non-negotiable 10: a bare
    `REMOVEFILTERS` strips the population too, which is how an excluded branch's
    prior year got into a denominator.
    """
    return f"VAR {var_name} = CALCULATE(MAX({column_ref}), REMOVEFILTERS({column_ref}))"


def latest_snapshot_filter(column_ref: str, var_name: str = "__latest_snapshot") -> str:
    """The filter argument pinning a query to one snapshot.

    `TREATAS` rather than an equality, per Non-negotiable 6: bare
    `KEEPFILTERS('T'[Col] = value)` reliably fails on these models with "single
    value for column cannot be determined".
    """
    return f"TREATAS({{{var_name}}}, {column_ref})"


def guard_semi_additive(verification: Any) -> str | None:
    """The reason a semi-additive measure must not be summed, if it must not be.

    Returns None when the measure is safe over time. Callers use this as a
    refusal, not a warning: Non-negotiable 11, and brief Part 6.7 makes a failed
    semi-additive claim a hard stop because the error is invisible downstream.
    """
    if verification is None:
        return None
    if getattr(verification, "safe_to_sum_over_time", False):
        return None
    return getattr(verification, "reason", "additivity over time was not established")


# --- labelling ----------------------------------------------------------------

def period_label(role: DateRole, latest: Any, span_label: str | None = None) -> str:
    """How a period is described in output.

    Non-negotiable 18: a snapshot measure says **"as at <date>"**, never a span.
    Labelling a snapshot with a range tells the reader it covers a period it
    does not - which is the same class of error as summing it across one.
    """
    if role is DateRole.SNAPSHOT:
        return f"as at {_date_text(latest)}" if latest is not None else "as at the latest snapshot"
    if span_label:
        return span_label
    return "over the period covered"


def _date_text(value: Any) -> str:
    text = str(value)
    # ISO timestamps come back from the REST API with a time component that is
    # always midnight for a date column; printing it would imply a precision
    # the data does not have.
    if "T" in text:
        text = text.split("T", 1)[0]
    return text.strip()
