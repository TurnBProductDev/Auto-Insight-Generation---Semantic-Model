"""Phase 5: memory-safe shadow mode for the rate-outlier lens (deterministic).

In ``shadow`` mode the rate lens runs end to end but its findings NEVER reach the
report or the memory store: they are diverted OUT of the reported candidate set
into a separate diagnostics channel/artifact so their yield can be measured
before the feature is promoted to ``report``. The memory store is read ONLY to
classify overlap; nothing is ever written (the safety-critical property). In
``report`` mode the findings stay in the pipeline (Phase 6 selects them) and the
artifact is still written for audit. In ``off`` mode there is nothing to do.

The divert (the safety step) runs before the diagnostics build, so a diagnostics
failure can never leak a rate finding into the report.
"""

from ..tools import file_io, insight_memory
from ..utils.json_utils import dumps  # noqa: F401  (kept for parity/debugging)


_RATE_FIELDS = (
    "segment", "metric", "bundle_id", "dimension", "direction", "evidence_query",
    "current", "prior", "impact_value",
    "reported_growth_pct", "log_growth", "peer_median_reported_pct",
    "peer_median_log_growth", "deviation_pct", "robust_z", "stat_basis",
    "peer_count", "prior_share", "current_share", "business_exposure",
    "impact_share", "relative_priority", "significance",
)


def _collect_items(result: dict) -> tuple:
    """Pull the three rate-lens outputs out of the detector result: standalone
    (genuinely-new) candidates, bridge-merged (corroborating) evidence, and
    small-peer ordinal context."""
    standalone, corroborating, ordinal = [], [], []
    for c in result.get("business_candidates", []) or []:
        if c.get("type") == "peer_growth_rate_outlier":
            standalone.append({"category": "standalone",
                               **{k: c.get(k) for k in _RATE_FIELDS}})
        elif c.get("type") == "change_contribution":
            if c.get("peer_rate_evidence"):
                corroborating.append({"category": "corroborating",
                                      "segment": c.get("segment"),
                                      "dimension": c.get("dimension"),
                                      "bundle_id": c.get("bundle_id"),
                                      **c["peer_rate_evidence"]})
            elif c.get("peer_rate_context"):
                ordinal.append({"category": "ordinal", "segment": c.get("segment"),
                                "dimension": c.get("dimension"), **c["peer_rate_context"]})
    return standalone, corroborating, ordinal


def _divert(result: dict) -> None:
    """Remove every rate-lens trace from the reported candidate set (shadow mode):
    drop standalone rate candidates and strip the merged/ordinal enrichments off
    bridge candidates, then re-number ids contiguously. After this the reported
    candidates are byte-for-byte what they would have been with the lens off."""
    kept = []
    for c in result.get("business_candidates", []) or []:
        if c.get("type") == "peer_growth_rate_outlier":
            continue
        c.pop("peer_rate_evidence", None)
        c.pop("has_rate_corroboration", None)
        c.pop("peer_rate_context", None)
        kept.append(c)
    result["business_candidates"] = kept
    dq = result.get("data_quality_candidates", []) or []
    for i, c in enumerate(kept + dq):
        c["id"] = f"cand_{i + 1:02d}_{c['type']}"


def _bridge_reported_before(item: dict, state: dict, records: dict,
                            contracts: dict, dataset_id, scope_h: str, anchor: str):
    """Was this segment already reported as a bridge (contribution) story? Uses the
    STABLE high-level story key (a rate finding and a bridge finding over the same
    metric bundle canonicalize to the same metric), so this answers 'is the rate
    finding just re-surfacing a known contribution story?'. Read-only. None when
    the store could not be read."""
    if records is None:
        return None
    contract = contracts.get(item.get("evidence_query")) or contracts.get(item.get("table")) or {}
    synthetic = {
        "level": "high", "type": "change_contribution",
        "metric": item.get("metric"), "segment": item.get("segment"),
        "table": item.get("evidence_query"),
        "impact_value": item.get("direction") or 0,
    }
    try:
        key, _ = insight_memory.story_components(synthetic, dataset_id, scope_h, contract, anchor)
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return None
    return key in records


def _rate_story_key(item: dict, records: dict, contracts: dict, dataset_id,
                    scope_h: str, anchor: str):
    """The rate finding's OWN Phase-7 suppression identity (the ``rate`` level
    story key) and whether it was already reported as a rate story. This is what
    the novelty filter suppresses/resurfaces on in report mode; surfacing it in
    the shadow artifact lets promotion review see how many standalone findings are
    genuinely new vs. repeats. READ-ONLY: shadow never writes memory and never
    marks a rate story seen (the Phase-5 safety property). ``(None, None)`` when
    the store could not be read or the key could not be built."""
    contract = contracts.get(item.get("evidence_query")) or contracts.get(item.get("table")) or {}
    synthetic = {
        "level": "rate", "type": "peer_growth_rate_outlier",
        "metric": item.get("metric"), "segment": item.get("segment"),
        "table": item.get("evidence_query"), "bundle_id": item.get("bundle_id"),
    }
    try:
        key, _ = insight_memory.story_components(synthetic, dataset_id, scope_h, contract, anchor)
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return None, None, None
    stored = records.get(key) if records is not None else None
    return key, (key in records if records is not None else None), stored


def _margins(item: dict, z_cut: float, exp_floor: float,
             imp_floor: float, prior_floor: float, flat_floor: float) -> dict:
    """How far the reading sits above each gate - a small margin flags a candidate
    whose survival is fragile to a modest threshold change (calibration risk)."""
    z = item.get("robust_z")
    exp = item.get("business_exposure")
    imp = item.get("impact_share")
    prior = item.get("prior_share")
    deviation = item.get("deviation_pct")
    is_flat_break = item.get("stat_basis") == "flat_peer_break"
    m = {
        "z_margin": (abs(z) - z_cut)
                    if isinstance(z, (int, float)) and not is_flat_break else None,
        "flat_break_margin": (abs(deviation) - flat_floor)
                             if is_flat_break and isinstance(deviation, (int, float)) else None,
        "exposure_margin": (exp - exp_floor) if isinstance(exp, (int, float)) else None,
        "impact_margin": (imp - imp_floor) if isinstance(imp, (int, float)) else None,
        "prior_margin": (prior - prior_floor) if isinstance(prior, (int, float)) else None,
    }
    thresholds = {"z_margin": z_cut, "flat_break_margin": flat_floor,
                  "exposure_margin": exp_floor,
                  "impact_margin": imp_floor, "prior_margin": prior_floor}
    fragile = any(v is not None and thresholds[k] > 0 and v < 0.2 * thresholds[k]
                  for k, v in m.items())
    m["fragile"] = fragile
    return m


def apply(state: dict, result: dict) -> dict:
    """Divert (shadow) and/or write the shadow diagnostics artifact. Returns the
    state channel update (only in shadow mode). Never raises - the divert happens
    first so a diagnostics failure cannot leak a finding into the report."""
    mode = str(state.get("insight_rate_outlier_mode", "off")).lower()
    if mode not in ("shadow", "report"):
        return {}

    standalone, corroborating, ordinal = _collect_items(result)
    rejections = list(result.get("rate_rejections", []) or [])

    updates = {}
    if mode == "shadow":
        _divert(result)                     # safety step FIRST (before diagnostics)
        updates["insight_rate_shadow_candidates"] = standalone + corroborating

    try:
        z_cut = float(state.get("insight_rate_z_cutoff", 3.0))
        exp_floor = float(state.get("insight_rate_exposure_floor_pct", 2.0))
        imp_floor = float(state.get("insight_rate_min_abs_impact_pct", 1.0))
        prior_floor = float(state.get("insight_rate_prior_share_floor_pct", 0.5))
        flat_floor = float(state.get("insight_rate_flat_min_pct", 10.0))
        memory, status = insight_memory.load_store(state)
        records = (memory.get("records") if status in ("ok", "empty") else None) or {}
        if status not in ("ok", "empty"):
            records = None
        contracts = state.get("insight_evidence_contracts", {}) or {}
        dataset_id = state.get("dataset_id")
        scope_h = insight_memory.scope_hash(state)
        anchor = insight_memory.period_anchor(state, insight_memory.derive_watermark(state))

        def _enrich(item):
            item = dict(item)
            item["bridge_reported_before"] = _bridge_reported_before(
                item, state, records, contracts, dataset_id, scope_h, anchor)
            if item.get("category") == "standalone":
                # A standalone finding has its own rate identity; a corroborating one
                # is suppressed via the bridge's contribution key, not a rate key.
                rk, seen, stored = _rate_story_key(
                    item, records, contracts, dataset_id, scope_h, anchor)
                item["rate_story_key"] = rk
                item["rate_reported_before"] = seen
                item["rate_would_resurface"] = (
                    insight_memory.resurface_check(
                        stored, item,
                        float(state.get("insight_re_alert_growth_pct", 50)))
                    if stored else False
                )
            item["threshold_margins"] = _margins(
                item, z_cut, exp_floor, imp_floor, prior_floor, flat_floor)
            return item

        standalone_items = [_enrich(i) for i in standalone]
        new_items = [i for i in standalone_items if i.get("rate_reported_before") is False]
        resurfacing_items = [i for i in standalone_items if i.get("rate_reported_before") is True
                             and i.get("rate_would_resurface")]
        seen_items = [i for i in standalone_items if i.get("rate_reported_before") is True
                      and not i.get("rate_would_resurface")]
        unknown_items = [i for i in standalone_items
                         if i.get("rate_reported_before") is None]
        corr_items = [_enrich(i) for i in corroborating]
        fragile = sum(1 for i in standalone_items + corr_items
                      if i["threshold_margins"].get("fragile"))
        peer_cov = state.get("insight_peer_coverage", {}) or {}

        report = {
            "mode": mode,
            "note": ("Shadow diagnostics for the rate-outlier lens. In shadow mode "
                     "these findings are NOT in the report and NOT in memory; this "
                     "artifact measures their yield for promotion review."),
            "cost": {
                "peer_dimensions_scanned": len(peer_cov),
                "peer_dimensions_eligible": sum(1 for v in peer_cov.values()
                                                if isinstance(v, dict) and v.get("eligible")),
                "peer_query_count": len(peer_cov),
            },
            "projected_effect_on_report": {
                "genuinely_new_count": len(new_items),
                "resurfacing_count": len(resurfacing_items),
                "already_seen_count": len(seen_items),
                "memory_unknown_count": len(unknown_items),
                "corroborating_count": len(corroborating),
                "ordinal_enrichment_count": len(ordinal),
                "relative_report_slots": 1,
                "would_compete_for_relative_slot": len(new_items) + len(resurfacing_items),
            },
            "memory": {
                "status": status,
                "bridge_overlap_uses": "stable high-level story key",
                "rate_identity_uses": "Phase-7 rate story key (level 'rate')",
                "note": ("'bridge_reported_before' flags overlap with a known "
                         "contribution story; 'rate_story_key'/'rate_reported_before' "
                         "(on genuinely-new items) are the rate finding's OWN Phase-7 "
                         "suppression identity and whether it was already reported as "
                         "a rate story. READ-ONLY: shadow wrote nothing to memory and "
                         "marked no rate story seen."),
            },
            "threshold_sensitivity": {
                "insight_rate_z_cutoff": z_cut,
                "insight_rate_exposure_floor_pct": exp_floor,
                "insight_rate_min_abs_impact_pct": imp_floor,
                "insight_rate_prior_share_floor_pct": prior_floor,
                "insight_rate_flat_min_pct": flat_floor,
                "fragile_candidate_count": fragile,
            },
            "genuinely_new": new_items,
            "resurfacing": resurfacing_items,
            "already_seen": seen_items,
            "memory_unknown": unknown_items,
            "corroborating": corr_items,
            "ordinal_enrichment": ordinal,
            "rejected": rejections,
        }
        file_io.write_json(state, "insight_rate_shadow.json", report)
    except Exception as exc:  # noqa: BLE001 - diagnostics are best-effort
        # The safety action (_divert) has already happened.  A failing artifact
        # writer must never escape and make the outer stat node discard the base
        # findings too. Try a minimal diagnostic once, then fail closed silently.
        try:
            file_io.write_json(state, "insight_rate_shadow.json",
                               {"mode": mode, "error": str(exc),
                                "standalone_count": len(standalone),
                                "corroborating_count": len(corroborating)})
        except Exception:  # noqa: BLE001
            pass
    return updates
