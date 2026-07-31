"""Deterministic DAX string builders for the summary focus deep-dive.

This module only assembles DAX *text* from primitives the deep-dive node has
already resolved from metadata (column references, measure names, member codes).
It runs no query, reads no state, and validates nothing - the node executes and
validates what these builders return. Every generated query obeys the model
guardrails documented in CLAUDE.md:

* never ``KEEPFILTERS('Table'[col] = "value")`` (it fails on this model) - member
  filtering is always ``TREATAS({...}, 'Table'[col])``;
* a ``SUMMARIZECOLUMNS`` breakdown always carries a ``TOPN`` row limit;
* comparison queries are scoped to the comparable population by the caller,
  which passes the population ``TREATAS`` in as a filter fragment.

The LLM never generates or repairs any of this DAX.
"""

from __future__ import annotations

from typing import Iterable, Sequence


def _escape_member(value) -> str:
    # DAX escapes a double quote inside a string literal by doubling it.
    return str("" if value is None else value).replace('"', '""')


def treatas(column_ref: str, members: Iterable) -> str:
    """A single-column ``TREATAS`` filter fragment over the given members."""
    items = ", ".join(f'"{_escape_member(m)}"' for m in members)
    return f"TREATAS({{{items}}}, {column_ref})"


def member_filter(column_ref: str, member) -> str:
    return treatas(column_ref, [member])


def scorecard(
    name: str,
    purpose: str,
    filters: Sequence[str],
    measures: Sequence[tuple[str, str]],
    contract_hint: dict | None = None,
) -> dict:
    """A grand-total ``ROW()`` scorecard for the focus.

    Each measure is evaluated inside a ``CALCULATE`` carrying the focus/population
    filters. A ``ROW()`` pack is all-or-nothing: if one measure throws the whole
    query fails, which the node treats as a non-fatal skipped drill.
    """
    parts = []
    for alias, measure in measures:
        if filters:
            expr = f"CALCULATE([{measure}], {', '.join(filters)})"
        else:
            expr = f"[{measure}]"
        parts.append(f'    "{_escape_member(alias)}", {expr}')
    dax = "EVALUATE\nROW(\n" + ",\n".join(parts) + "\n)"
    return {
        "name": name,
        "purpose": purpose,
        "dax": dax,
        "contract_hint": dict(contract_hint or {}),
    }


def breakdown(
    name: str,
    purpose: str,
    group_col_ref: str,
    filters: Sequence[str],
    measures: Sequence[tuple[str, str]],
    sort_measure: str,
    rows: int,
    contract_hint: dict | None = None,
    parent_col_ref: str | None = None,
) -> dict:
    """A row-bounded breakdown of the focus by ``group_col_ref``.

    Ordered by the absolute value of ``sort_measure`` so the largest +/- movers
    surface. A completeness filter drops rows blank on the first measure.
    """
    cols = [f'"{_escape_member(alias)}", [{measure}]' for alias, measure in measures]
    first_alias, first_measure = measures[0]
    sort_alias = next((alias for alias, measure in measures if measure == sort_measure), first_alias)
    if parent_col_ref:
        # These diagnostics run inside the same bounded breakdown query.  They
        # prove parent filtering/nestedness/reconciliation without spending a
        # separate REST call and are stripped before evidence reaches the LLM.
        cols.extend([
            f'"__focus_total", CALCULATE([{first_measure}], REMOVEFILTERS({group_col_ref}))',
            (
                f'"__global_total", CALCULATE([{first_measure}], '
                f'REMOVEFILTERS({group_col_ref}), REMOVEFILTERS({parent_col_ref}))'
            ),
            (
                f'"__parent_count", CALCULATE(DISTINCTCOUNT({parent_col_ref}), '
                f'REMOVEFILTERS({parent_col_ref}))'
            ),
        ])
    filt = "".join(f"{fragment}, " for fragment in filters)
    inner = f"SUMMARIZECOLUMNS({group_col_ref}, {filt}{', '.join(cols)})"
    filtered = f"FILTER({inner}, NOT ISBLANK([{first_alias}]))"
    with_sort = f'ADDCOLUMNS({filtered}, "abs_sort", ABS([{sort_alias}]))'
    dax = f"EVALUATE\nTOPN({int(rows)}, {with_sort}, [abs_sort], DESC)"
    return {
        "name": name,
        "purpose": purpose,
        "dax": dax,
        "contract_hint": dict(contract_hint or {}),
    }


def universe_scan(
    name: str,
    purpose: str,
    group_col_ref: str,
    parent_col_refs: Sequence[str],
    filters: Sequence[str],
    current_measure: str,
    prior_measure: str,
    change_measure: str | None,
    pool_rows: int,
    contract_hint: dict | None = None,
) -> dict:
    """One bounded per-role universe scan with full-set broadcast diagnostics.

    Groups by the full hierarchy path (``parent_col_refs`` broad->narrow, then
    ``group_col_ref``) inside the comparable population ``filters``. Diagnostics
    are computed *inside* SUMMARIZECOLUMNS - the proven ``breakdown`` pattern -
    so each is evaluated with the row's parent columns still in filter context
    and only the leaf removed. That makes the sibling gross/signed change and the
    parent change *per parent path* (§10), not global, while the full member set
    (not the returned TOPN) drives the denominator. Columns are stripped before
    the LLM ever sees a row.

    ``change_measure`` is used when the model exposes one, else the change is the
    additive difference of the current and prior measures.
    """
    change_expr = f"[{change_measure}]" if change_measure else f"([{current_measure}] - [{prior_measure}])"
    path_cols = list(parent_col_refs) + [group_col_ref]
    group_by = ", ".join(path_cols)
    filt = "".join(f"{fragment}, " for fragment in filters)
    remove_all_path = ", ".join(f"REMOVEFILTERS({ref})" for ref in path_cols)
    cols = [
        f'"__cur", [{current_measure}]',
        f'"__pri", [{prior_measure}]',
        f'"__chg", {change_expr}',
        (
            f'"__gross_sibling_change", CALCULATE(SUMX(VALUES({group_col_ref}), '
            f'ABS({change_expr})), REMOVEFILTERS({group_col_ref}))'
        ),
        (
            f'"__signed_sibling_change", CALCULATE(SUMX(VALUES({group_col_ref}), '
            f'{change_expr}), REMOVEFILTERS({group_col_ref}))'
        ),
        f'"__parent_change", CALCULATE({change_expr}, REMOVEFILTERS({group_col_ref}))',
        f'"__overall_current", CALCULATE([{current_measure}], {remove_all_path})',
        (
            f'"__full_member_count", CALCULATE(DISTINCTCOUNT({group_col_ref}), '
            f'REMOVEFILTERS({group_col_ref}))'
        ),
    ]
    inner = f"SUMMARIZECOLUMNS({group_by}, {filt}{', '.join(cols)})"
    filtered = f"FILTER({inner}, NOT ISBLANK([__cur]))"
    ranked = f'ADDCOLUMNS({filtered}, "__abs", ABS([__chg]))'
    dax = f"EVALUATE\nTOPN({int(pool_rows)}, {ranked}, [__abs], DESC)"
    return {
        "name": name,
        "purpose": purpose,
        "dax": dax,
        "contract_hint": dict(contract_hint or {}),
    }


def period_trend(
    name: str,
    purpose: str,
    time_col_ref: str,
    filters: Sequence[str],
    measures: Sequence[tuple[str, str]],
    rows: int,
    contract_hint: dict | None = None,
) -> dict:
    """A bounded, time-ordered and reconciliation-auditable focus series."""
    cols = ", ".join(f'"{_escape_member(alias)}", [{measure}]' for alias, measure in measures)
    first_alias, first_measure = measures[0]
    filt = "".join(f"{fragment}, " for fragment in filters)
    inner = f"SUMMARIZECOLUMNS({time_col_ref}, {filt}{cols})"
    focus_total = (
        f"CALCULATE([{first_measure}], {', '.join(filters)})"
        if filters else f"[{first_measure}]"
    )
    # Select the most recent N periods, then explicitly order the returned rows
    # oldest-to-newest. Diagnostic totals prove the FULL (pre-TOPN) time series
    # partitions the same selected focus; they are stripped before LLM use.
    dax = (
        "EVALUATE\n"
        f"VAR __series = {inner}\n"
        f"VAR __recent = TOPN({int(rows)}, __series, {time_col_ref}, DESC)\n"
        f"VAR __series_total = SUMX(__series, [{first_alias}])\n"
        f"VAR __focus_total = {focus_total}\n"
        "RETURN ADDCOLUMNS(__recent, \"__series_total\", __series_total, "
        "\"__focus_total\", __focus_total)\n"
        f"ORDER BY {time_col_ref} ASC"
    )
    return {
        "name": name,
        "purpose": purpose,
        "dax": dax,
        "contract_hint": dict(contract_hint or {}),
    }
