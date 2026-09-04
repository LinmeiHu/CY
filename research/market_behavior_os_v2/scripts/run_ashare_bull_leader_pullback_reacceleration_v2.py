#!/usr/bin/env python3
"""Bull leader first-pullback reacceleration, with causal market/industry state."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-LEADER-FIRST-PULLBACK-REACCELERATION-V2"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_leader_first_pullback_reacceleration_v2")

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_40_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

DAILY = v1.DAILY
REGIME = v1.SOURCE_REGIME
INDUSTRY = v1.INDUSTRY_PANEL
PROFILES = {
    "H10_NEXT_OPEN": {"horizon": 10, "target": None},
    "T10_H15_NO_STOP": {"horizon": 15, "target": 0.10},
    "T15_H15_NO_STOP": {"horizon": 15, "target": 0.15},
}
RULES = {
    "R1_RUN30_D5_20_U3": {
        "runup": 0.30,
        "drawdown_low": -0.20,
        "drawdown_high": -0.05,
        "step": 0.03,
        "close_location": 0.70,
        "turnover_expansion": 1.20,
    },
    "R2_RUN40_D8_20_U3": {
        "runup": 0.40,
        "drawdown_low": -0.20,
        "drawdown_high": -0.08,
        "step": 0.03,
        "close_location": 0.70,
        "turnover_expansion": 1.20,
    },
    "R3_RUN30_D5_20_U4": {
        "runup": 0.30,
        "drawdown_low": -0.20,
        "drawdown_high": -0.05,
        "step": 0.04,
        "close_location": 0.75,
        "turnover_expansion": 1.50,
    },
    "R4_RUN40_D8_25_U4": {
        "runup": 0.40,
        "drawdown_low": -0.25,
        "drawdown_high": -0.08,
        "step": 0.04,
        "close_location": 0.75,
        "turnover_expansion": 1.50,
    },
}
DISCOVERY = tuple(range(2014, 2019))
CONFIRMATION = (2019, 2020, 2021)
DIAGNOSTIC = (2022, 2023)
YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail-closed V2 error."""


def sha256(path: Path) -> str:
    return v1.sha256(path)


def write_json(path: Path, value: Any) -> None:
    v1.write_json(path, value)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    v1.write_parquet(frame, path)


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "In a causally observed broad bull market with positive majority "
            "industry participation, a recent leader's first high-location, "
            "turnover-backed break above its five-session approach ceiling after "
            "an orderly pullback represents renewed active demand rather than a "
            "downward-gap repair."
        ),
        "market_gate": v1.contract_value()["market_regime"],
        "industry_gate": (
            "PIT industry n20 >= 5, median completed ret20 > 0, and positive-ret20 "
            "share > 0.50 at signal close"
        ),
        "shared_semantics": {
            "leader_runup": "prior20 coordinate high / prior60 coordinate low - 1",
            "pullback": "previous coordinate close / prior20 coordinate high - 1",
            "reacceleration": (
                "current completed close first crosses above prior5 coordinate high; "
                "current step return, close location and turnover expansion satisfy rule"
            ),
            "trend_integrity": "current close > completed-session lag20 close",
            "history": "exactly 60 prior valid completed same-symbol sessions",
        },
        "bounded_rules": RULES,
        "profiles": PROFILES,
        "entry": "first legal daily open after signal, within three market sessions",
        "exit": (
            "standing target from first T+1 session through the causal horizon "
            "decision; otherwise first legal open after the horizon decision"
        ),
        "cost": 0.004,
        "selection": {
            "discovery_years": list(DISCOVERY),
            "minimum_completed": 300,
            "minimum_positive_years": 3,
            "mean_holding_max": 15,
            "order": [
                "median annual discovery mean",
                "pooled discovery mean",
                "lower severe_loss10",
                "fewer strict trigger requirements",
                "shorter profile",
            ],
        },
        "portfolio": v1.contract_value()["portfolio"],
        "required_gate": v1.contract_value()["required_gate"],
        "governance": {
            "stage_a_before_outcomes": True,
            "no_post_2023_signal_or_feature": True,
            "2024_rows_only_close_pre_2024_trade": True,
            "no_same_bar_fill": True,
            "downward_gap_identity_used": False,
        },
    }


def persist_contract() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_CANDIDATE_AND_TRANSLATION_FREEZE",
            "contract_sha256": sha256(CONTRACT),
            "v1_execution_dependency_sha256": sha256(Path(v1.__file__)),
            "source_hashes": {
                "daily": sha256(DAILY),
                "regime": sha256(REGIME),
                "industry": sha256(INDUSTRY),
            },
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH d0 AS (
                SELECT *,
                  lag(coord_close) OVER w AS prev_close,
                  max(coord_high) OVER w20 AS prior20_high,
                  max(coord_high) OVER w5 AS prior5_high,
                  min(coord_low) OVER w60 AS prior60_low,
                  avg(turnover_fraction) OVER w20 AS prior20_turnover,
                  count(*) OVER w60 AS prior60_n
                FROM read_parquet('{DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st
                  AND causal_industry IS NOT NULL
                WINDOW
                  w AS (PARTITION BY symbol ORDER BY trade_date),
                  w5 AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING
                  ),
                  w20 AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING
                  ),
                  w60 AS (
                    PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING
                  )
              ), f AS (
                SELECT d0.*,
                  prev_close/prior20_high-1 AS pre_drawdown,
                  prior20_high/prior60_low-1 AS prior_runup,
                  (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS signal_close_location,
                  turnover_fraction/nullif(prior20_turnover,0) AS signal_turnover_expansion
                FROM d0
                WHERE trade_date>=DATE '2014-01-01' AND prior60_n=60
              ), x AS (
                SELECT f.*,r.market_regime,r.latest_source_timestamp AS market_latest_source,
                  i.industry_median_ret20,i.industry_positive_ret20_share,
                  i.industry_median_ret60,i.industry_n20,
                  i.latest_source_timestamp AS industry_latest_source,
                  ret20-i.industry_median_ret20 AS stock_minus_industry_ret20
                FROM f
                JOIN read_parquet('{REGIME}') r USING(trade_date)
                JOIN read_parquet('{INDUSTRY}') i USING(trade_date,causal_industry)
                WHERE r.market_regime='BULL'
                  AND i.industry_n20>=5
                  AND i.industry_median_ret20>0
                  AND i.industry_positive_ret20_share>0.50
                  AND coord_close>lag20_close
                  AND coord_close>prior5_high
                  AND prev_close<=prior5_high
              )
              SELECT *,
                'BLPR-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,
                decision_at AS feature_latest_timestamp,
                prior20_high AS platform_high,
                prior_runup>=0.30 AND pre_drawdown BETWEEN -0.20 AND -0.05
                  AND step_return>=0.03 AND signal_close_location>=0.70
                  AND signal_turnover_expansion>=1.20 AS pass_R1_RUN30_D5_20_U3,
                prior_runup>=0.40 AND pre_drawdown BETWEEN -0.20 AND -0.08
                  AND step_return>=0.03 AND signal_close_location>=0.70
                  AND signal_turnover_expansion>=1.20 AS pass_R2_RUN40_D8_20_U3,
                prior_runup>=0.30 AND pre_drawdown BETWEEN -0.20 AND -0.05
                  AND step_return>=0.04 AND signal_close_location>=0.75
                  AND signal_turnover_expansion>=1.50 AS pass_R3_RUN30_D5_20_U4,
                prior_runup>=0.40 AND pre_drawdown BETWEEN -0.25 AND -0.08
                  AND step_return>=0.04 AND signal_close_location>=0.75
                  AND signal_turnover_expansion>=1.50 AS pass_R4_RUN40_D8_25_U4,
                signal_turnover_expansion AS turnover_expansion
              FROM x
              WHERE pass_R1_RUN30_D5_20_U3 OR pass_R2_RUN40_D8_20_U3
                OR pass_R3_RUN30_D5_20_U4 OR pass_R4_RUN40_D8_25_U4
              ORDER BY trade_date,symbol
            ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in (
        "trade_date",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    if frame.event_id.duplicated().any():
        raise ResearchError("duplicate event identity")
    causal = (
        frame.available_at.le(frame.decision_at)
        & frame.market_latest_source.le(frame.decision_at)
        & frame.industry_latest_source.le(frame.decision_at)
        & frame.feature_latest_timestamp.le(frame.decision_at)
    )
    if not causal.all():
        raise ResearchError("post-decision feature timestamp")
    return frame


def blind_sample(frame: pd.DataFrame, count: int = 40) -> pd.DataFrame:
    sample = frame.copy()
    sample["year"] = sample.signal_date.dt.year
    sample["hash_order"] = sample.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    rows = [
        part.sort_values("hash_order").head(2)
        for _, part in sample.groupby(["year", "sleeve"], sort=True)
    ]
    chosen = pd.concat(rows, ignore_index=True).sort_values("hash_order").head(count)
    if len(chosen) < count:
        rest = sample.loc[~sample.event_id.isin(chosen.event_id)]
        chosen = pd.concat(
            [chosen, rest.sort_values("hash_order").head(count - len(chosen))],
            ignore_index=True,
        )
    chosen = chosen.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    chosen.insert(0, "chart_id", [f"BULL-PULLBACK-{i:03d}" for i in range(1, len(chosen) + 1)])
    chosen.to_csv(BLIND_INDEX, index=False)
    return chosen


def render_blind_charts(sample: pd.DataFrame) -> None:
    BLIND_PDF.parent.mkdir(parents=True, exist_ok=True)
    symbols = pd.DataFrame({"symbol": sorted(sample.symbol.unique())})
    con = duckdb.connect()
    con.register("symbols", symbols)
    daily = con.execute(
        f"""
        SELECT d.trade_date,d.symbol,d.coord_open,d.coord_high,d.coord_low,
          d.coord_close,d.turnover_fraction,d.ret20
        FROM read_parquet('{DAILY}') d JOIN symbols s USING(symbol)
        WHERE d.trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    con.close()
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    groups = {key: part.reset_index(drop=True) for key, part in daily.groupby("symbol")}
    industry = pd.read_parquet(INDUSTRY)
    industry["trade_date"] = pd.to_datetime(industry.trade_date)
    regime = pd.read_parquet(REGIME)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    with v1.PdfPages(BLIND_PDF) as pdf:
        for event in sample.itertuples(index=False):
            part = groups[event.symbol]
            positions = np.flatnonzero(
                part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy()
            )
            if len(positions) != 1:
                raise ResearchError(f"chart signal row missing {event.event_id}")
            end = int(positions[0])
            stock = part.iloc[max(0, end - 119) : end + 1].copy()
            start_date = stock.trade_date.min()
            market = regime.loc[regime.trade_date.between(start_date, event.signal_date)].copy()
            ind = industry.loc[
                industry.causal_industry.eq(event.causal_industry)
                & industry.trade_date.between(start_date, event.signal_date)
            ].copy()
            fig, axes = v1.plt.subplots(
                4,
                1,
                figsize=(11.7, 8.3),
                gridspec_kw={"height_ratios": [2.4, 0.7, 1, 1]},
            )
            ax = axes[0]
            x = v1.mdates.date2num(stock.trade_date)
            colors = np.where(
                stock.coord_close.ge(stock.coord_open).to_numpy(),
                "#dc2626",
                "#059669",
            )
            ax.vlines(
                x,
                stock.coord_low,
                stock.coord_high,
                color=colors,
                linewidth=0.65,
            )
            body_low = np.minimum(stock.coord_open, stock.coord_close)
            body_height = np.maximum(
                np.abs(stock.coord_close - stock.coord_open),
                stock.coord_close.abs() * 0.0005,
            )
            ax.bar(
                x,
                body_height,
                bottom=body_low,
                width=0.65,
                color=colors,
                edgecolor=colors,
                linewidth=0.3,
                label="Daily candle",
            )
            ax.axvline(
                pd.Timestamp(event.signal_date),
                color="#dc2626",
                linestyle="--",
                label="Signal close",
            )
            ax.axhline(
                float(event.prior20_high),
                color="#ea580c",
                linestyle=":",
                label="Prior 20d high",
            )
            ax.set_title(
                f"{event.chart_id} | {event.symbol} | {event.sleeve} | {event.causal_industry}",
                fontproperties=v1.CJK_FONT,
            )
            ax.legend(loc="upper left", ncol=3, fontsize=8)
            ax.grid(alpha=0.2)
            axes[1].bar(
                stock.trade_date,
                stock.turnover_fraction,
                color=colors,
                width=0.75,
                alpha=0.7,
            )
            axes[1].axvline(pd.Timestamp(event.signal_date), color="#dc2626", linestyle="--")
            axes[1].set_ylabel("Turnover")
            axes[1].grid(alpha=0.2)
            axes[2].plot(
                market.trade_date,
                market.market_median_ret20,
                label="Market median ret20",
                color="#166534",
            )
            axes[2].plot(
                market.trade_date,
                market.market_median_ret60,
                label="Market median ret60",
                color="#0f766e",
            )
            axes[2].axhline(0, color="black", linewidth=0.7)
            axes[2].set_ylabel("Market")
            axes[2].legend(loc="upper left", fontsize=8, ncol=2)
            axes[2].grid(alpha=0.2)
            axes[3].plot(
                ind.trade_date,
                ind.industry_median_ret20,
                label="Industry median ret20",
                color="#7c3aed",
            )
            axes[3].plot(
                stock.trade_date,
                stock.ret20,
                label="Stock ret20",
                color="#b45309",
            )
            axes[3].axhline(0, color="black", linewidth=0.7)
            axes[3].set_ylabel("Industry / stock")
            axes[3].legend(loc="upper left", fontsize=8, ncol=2)
            axes[3].grid(alpha=0.2)
            axes[3].xaxis.set_major_locator(v1.mdates.MonthLocator(interval=1))
            axes[3].xaxis.set_major_formatter(v1.mdates.DateFormatter("%Y-%m"))
            fig.text(
                0.01,
                0.01,
                "Signal-only chart. BULL at close. "
                f"Prior run-up {event.prior_runup:+.1%}; "
                f"pre-signal drawdown {event.pre_drawdown:+.1%}; "
                f"industry median20 {event.industry_median_ret20:+.1%}. "
                "No post-signal bar.",
                fontsize=8,
            )
            fig.tight_layout(rect=[0, 0.035, 1, 1])
            pdf.savefig(fig, dpi=160)
            v1.plt.close(fig)


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    frame = build_candidates()
    sample = blind_sample(frame)
    render_blind_charts(sample)
    coverage = {
        rule: {
            "count": int(frame[f"pass_{rule}"].sum()),
            "annual": (
                frame.loc[frame[f"pass_{rule}"]]
                .groupby(frame.loc[frame[f"pass_{rule}"], "signal_date"].dt.year)
                .size()
                .reindex(YEARS, fill_value=0)
                .astype(int)
                .to_dict()
            ),
        }
        for rule in RULES
    }
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(
            frame.feature_latest_timestamp.gt(frame.decision_at).sum()
        ),
        "market_after_decision_count": int(frame.market_latest_source.gt(frame.decision_at).sum()),
        "industry_after_decision_count": int(
            frame.industry_latest_source.gt(frame.decision_at).sum()
        ),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
        "outcomes_opened": False,
    }
    if any(value for key, value in audit.items() if key != "outcomes_opened"):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "v1_dependency_sha256": sha256(Path(v1.__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "blind_pdf_sha256": sha256(BLIND_PDF),
        "candidate_count": len(frame),
        "coverage": coverage,
        "audit": audit,
    }
    write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> None:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "v1_dependency_sha256": sha256(Path(v1.__file__)),
        "candidate_sha256": sha256(CANDIDATES),
        "blind_pdf_sha256": sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift: {drift}")


def build_outcomes(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    daily = v1.load_trade_daily(frame.symbol.astype(str).unique().tolist())
    groups = {
        str(symbol): part.sort_values("trade_date").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in frame.itertuples(index=False):
        part = groups[str(event.symbol)]
        signal_positions = np.flatnonzero(
            part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy()
        )
        if len(signal_positions) != 1:
            raise ResearchError(f"missing signal day {event.event_id}")
        signal_pos = int(signal_positions[0])
        lineage = float(event.invalid_step_cum)
        entry_pos = None
        for pos in range(signal_pos + 1, len(part)):
            row = part.iloc[pos]
            if int(row.cal_idx) > int(event.cal_idx) + 3:
                break
            if v1.legal_buy(row, lineage):
                entry_pos = pos
                break
        for profile, params in PROFILES.items():
            base = {
                "event_id": event.event_id,
                "symbol": event.symbol,
                "sleeve": event.sleeve,
                "signal_date": event.signal_date,
                "signal_cal_idx": int(event.cal_idx),
                "profile": profile,
            }
            if entry_pos is None:
                rows.append({**base, "status": "NO_LEGAL_ENTRY"})
                continue
            entry = part.iloc[entry_pos]
            entry_price = float(entry.coord_open)
            horizon_idx = int(entry.cal_idx) + int(params["horizon"])
            decision_pos = None
            target_choice: tuple[int, float] | None = None
            target = None if params["target"] is None else entry_price * (1 + params["target"])
            for pos in range(entry_pos + 1, len(part)):
                row = part.iloc[pos]
                state_valid = v1.legal_state(row, lineage)
                if target is not None and state_valid and float(row.coord_high) >= target:
                    target_choice = (pos, target)
                    break
                if int(row.cal_idx) >= horizon_idx and state_valid:
                    decision_pos = pos
                    break
            if target_choice is not None:
                exit_pos, exit_price = target_choice
                exit_reason = f"TARGET_{int(params['target'] * 100)}"
                exit_decision_idx = int(entry.cal_idx)
            else:
                if decision_pos is None:
                    rows.append(
                        {
                            **base,
                            "status": "INCOMPLETE_OUTCOME_TAIL",
                            "entry_date": entry.trade_date,
                            "entry_cal_idx": int(entry.cal_idx),
                            "entry_price": entry_price,
                        }
                    )
                    continue
                exit_pos = None
                for pos in range(decision_pos + 1, len(part)):
                    if v1.legal_sell_open(part.iloc[pos], lineage):
                        exit_pos = pos
                        break
                if exit_pos is None:
                    rows.append(
                        {
                            **base,
                            "status": "INCOMPLETE_OUTCOME_TAIL",
                            "entry_date": entry.trade_date,
                            "entry_cal_idx": int(entry.cal_idx),
                            "entry_price": entry_price,
                        }
                    )
                    continue
                exit_price = float(part.iloc[exit_pos].coord_open)
                exit_reason = f"H{params['horizon']}_TIME_STOP"
                exit_decision_idx = int(part.iloc[decision_pos].cal_idx)
            exit_row = part.iloc[exit_pos]
            if part.iloc[entry_pos : exit_pos + 1].invalid_step_cum.ne(lineage).any():
                rows.append(
                    {
                        **base,
                        "status": "INVALID_COORDINATE_LINEAGE_AFTER_ENTRY",
                        "entry_date": entry.trade_date,
                        "entry_cal_idx": int(entry.cal_idx),
                        "entry_price": entry_price,
                    }
                )
                continue
            gross = exit_price / entry_price - 1
            rows.append(
                {
                    **base,
                    "status": "COMPLETED",
                    "entry_date": entry.trade_date,
                    "entry_cal_idx": int(entry.cal_idx),
                    "entry_price": entry_price,
                    "exit_date": exit_row.trade_date,
                    "exit_cal_idx": int(exit_row.cal_idx),
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "exit_decision_cal_idx": exit_decision_idx,
                    "holding_sessions": int(exit_row.cal_idx) - int(entry.cal_idx),
                    "gross_return": gross,
                    "net_return": gross - 0.004,
                }
            )
    outcomes = pd.DataFrame(rows)
    for column in ("signal_date", "entry_date", "exit_date"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    write_parquet(outcomes, OUTCOMES)
    audit = {
        "signal_bar_fill_count": int(
            (outcomes.entry_date.notna() & outcomes.entry_date.le(outcomes.signal_date)).sum()
        ),
        "t1_same_day_exit_count": int(
            (
                outcomes.status.eq("COMPLETED") & outcomes.exit_cal_idx.le(outcomes.entry_cal_idx)
            ).sum()
        ),
    }
    return outcomes, audit


def summary(frame: pd.DataFrame) -> dict[str, Any]:
    return v1.summary(frame)


def select_candidate(
    outcomes: pd.DataFrame, candidates: pd.DataFrame
) -> tuple[pd.DataFrame, pd.Series]:
    joined = outcomes.merge(
        candidates[
            [
                "event_id",
                *[f"pass_{rule}" for rule in RULES],
            ]
        ],
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    rows = []
    for rule in RULES:
        for profile in PROFILES:
            part = joined.loc[
                joined.profile.eq(profile)
                & joined[f"pass_{rule}"]
                & joined.signal_date.dt.year.isin(DISCOVERY)
            ]
            metrics = summary(part)
            annual = {
                str(year): summary(part.loc[part.signal_date.dt.year.eq(year)])
                for year in DISCOVERY
            }
            means = [
                value["mean_net"] for value in annual.values() if value["mean_net"] is not None
            ]
            rows.append(
                {
                    "rule": rule,
                    "profile": profile,
                    **metrics,
                    "positive_years": sum(value > 0 for value in means),
                    "median_annual_mean_net": float(np.median(means)),
                    "annual_json": json.dumps(annual, sort_keys=True),
                }
            )
    table = pd.DataFrame(rows)
    eligible = table.loc[
        table.completed_trades.ge(300)
        & table.positive_years.ge(3)
        & table.mean_holding_sessions.le(15)
    ].copy()
    if eligible.empty:
        raise ResearchError("no V2 discovery candidate meets frozen support")
    eligible["rule_order"] = eligible.rule.map({rule: index for index, rule in enumerate(RULES)})
    eligible["profile_order"] = eligible.profile.map(
        {profile: index for index, profile in enumerate(PROFILES)}
    )
    eligible = eligible.sort_values(
        [
            "median_annual_mean_net",
            "mean_net",
            "severe_loss10",
            "rule_order",
            "profile_order",
        ],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    )
    return table, eligible.iloc[0]


def run_stage_b() -> dict[str, Any]:
    verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    outcomes, audit = build_outcomes(candidates)
    if any(audit.values()):
        raise ResearchError(str(audit))
    table, selected = select_candidate(outcomes, candidates)
    rule = str(selected.rule)
    profile = str(selected.profile)
    selected_all = outcomes.merge(
        candidates[
            [
                "event_id",
                "industry_positive_ret20_share",
                "stock_minus_industry_ret20",
                "turnover_expansion",
                f"pass_{rule}",
            ]
        ],
        on="event_id",
        how="left",
        validate="many_to_one",
    )
    selected_all = selected_all.loc[
        selected_all.profile.eq(profile) & selected_all[f"pass_{rule}"]
    ].copy()
    daily = v1.load_trade_daily(selected_all.symbol.astype(str).unique().tolist())
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, _nav, portfolio = v1.replay_portfolio(selected_all, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    annual = v1.annual_summary(accepted.assign(status="COMPLETED"))
    full = summary(accepted.assign(status="COMPLETED"))
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "trades_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_ge_3pct": full["mean_net"] >= 0.03,
        "mean_holding_le_15": full["mean_holding_sessions"] <= 15,
        "2019_2021_each_positive": all(annual[str(y)]["mean_net"] > 0 for y in CONFIRMATION),
        "2022_positive": annual["2022"]["mean_net"] > 0,
        "2023_positive": annual["2023"]["mean_net"] > 0,
        "mean_ex_best5_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"]
        <= 0.25,
    }
    result = {
        "experiment": EXPERIMENT,
        "selected_rule": rule,
        "selected_profile": profile,
        "candidate_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "average_trades_per_year": len(accepted) / 10,
        "full_2014_2023": full,
        "annual": annual,
        "portfolio": portfolio,
        "concentration": concentration,
        "gate": gate,
        "audit": {
            **audit,
            "feature_after_decision_count": int(
                candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()
            ),
            "post_2023_signal_count": int(
                candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()
            ),
            "repository_2024_plus_rows_used_for_signal_or_feature": 0,
            "repository_2024_rows_used_only_for_pre_2024_trade_resolution": True,
        },
        "verdict": "BULL_PULLBACK_REACCELERATION_EDGE"
        if all(gate.values())
        else "BULL_PULLBACK_REACCELERATION_FAILS_TARGET",
        "hashes": {
            "outcomes": sha256(OUTCOMES),
            "accepted": sha256(ACCEPTED),
            "skipped": sha256(SKIPPED),
            "nav": sha256(NAV),
        },
    }
    write_json(RESULT, result)
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        f"Selected `{rule}` with `{profile}`.",
        "",
        "|Year|Trades|Mean net|Median net|Win|Mean hold|",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for year, values in annual.items():
        lines.append(
            f"|{year}|{values['completed_trades']}|{v1.pct(values['mean_net'])}|"
            f"{v1.pct(values['median_net'])}|{v1.pct(values['win_rate'])}|"
            f"{values['mean_holding_sessions']:.2f}|"
        )
    lines += ["", f"Gate: `{json.dumps(gate, sort_keys=True)}`.", ""]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, default=str))
    else:
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
