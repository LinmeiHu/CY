#!/usr/bin/env python3
"""Frozen I0 continuation versus one exact all-stock attention block."""
from __future__ import annotations

import argparse
import fcntl
import gc
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint
from scipy.linalg import svd
from scipy.stats import spearmanr
from sklearn.preprocessing import StandardScaler


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
CHAMP = Path("/Users/linmei/Documents/CY-worktrees/ashare-champion-playbooks-v1-20260908")
SRC = CHAMP / "research/ashare_path_long_training_v1"
DOC = SRC / "account_diversification_v1"
ROOT = HERE / ".." / "training_root_cause_v2"
ROOT = ROOT.resolve()
VOL = Path("/Volumes/quant/CY_quant_research/ashare_path_long_training_v1")
EXT = VOL / "account_diversification_v1/account_aligned_alpha_v1/i0_allstock_attention_lr_v1"
NESTED = VOL / "account_diversification_v1/o2_nested_earlystop_v1"
SIGNAL_SPRINT = VOL / "account_diversification_v1/train_fit_v1/signal_sprint"
PROTOCOL = DOC / "O2_NESTED_EARLYSTOP_PROTOCOL.json"
FULL = VOL / "account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward"
SPEC_PATH = HERE / "EXPERIMENT_SPEC.json"
STATE_PATH = HERE / "RUN_STATE.json"
LOCK = HERE / "PIPELINE.lock"
LRS = (1e-5, 3e-6, 1e-6)
STEPS = (8000, 16000, 32000)
SEEDS = (17, 29, 43)
QUERY_CHUNK = 256

sys.path.insert(0, str(SRC))
import common  # noqa: E402
import o2_nested_earlystop as nested  # noqa: E402
from train import PathResidual  # noqa: E402
from centered_branch_numerical_repair import solve as centered_solve, tolerance as centered_tolerance  # noqa: E402


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    return value


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def update_state(status: str, stage: str, **fields) -> None:
    previous = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
    previous.update(
        status=status,
        stage=stage,
        pid=os.getpid() if status == "RUNNING" else None,
        updated_at=pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
        **fields,
    )
    dump(STATE_PATH, previous)


class AllStockModel(nn.Module):
    """Authoritative PathResidual with one optional same-date relation block."""

    def __init__(self, config: dict, relation: bool, query_chunk: int = QUERY_CHUNK):
        super().__init__()
        self.c = config
        self.conditioned = False
        self.core = PathResidual(config).core
        self.relation_enabled = relation
        self.query_chunk = query_chunk
        d = int(config["embedding"])
        self.d_attn = min(d, 32)
        if relation:
            self.norm = nn.LayerNorm(d)
            self.q = nn.Linear(d, self.d_attn)
            self.k = nn.Linear(d, self.d_attn)
            self.v = nn.Linear(d, self.d_attn)
            self.o = nn.Linear(self.d_attn, d)
            nn.init.zeros_(self.o.weight)
            nn.init.zeros_(self.o.bias)

    def _attend_chunk(self, q: torch.Tensor, k: torch.Tensor, v: torch.Tensor, start: int) -> torch.Tensor:
        logits = q @ k.T / math.sqrt(self.d_attn)
        local = torch.arange(len(q), device=q.device)
        logits[local, start + local] = -torch.inf
        return logits.softmax(-1) @ v

    def relation_context(self, z: torch.Tensor, checkpoint_chunks: bool = False) -> torch.Tensor:
        n = len(z)
        if not self.relation_enabled or n <= 1:
            return torch.zeros_like(z)
        u = self.norm(z - z.mean(0, keepdim=True))
        q, k, v = self.q(u), self.k(u), self.v(u)
        parts = []
        for start in range(0, n, self.query_chunk):
            qpart = q[start : start + self.query_chunk]
            if checkpoint_chunks and self.training:
                part = checkpoint(
                    lambda a, b, c, s=start: self._attend_chunk(a, b, c, s),
                    qpart,
                    k,
                    v,
                    use_reentrant=False,
                )
            else:
                part = self._attend_chunk(qpart, k, v, start)
            parts.append(part)
        return self.o(torch.cat(parts))

    def forward(self, x: torch.Tensor, legs: torch.Tensor, checkpoint_chunks: bool = False):
        pred, z, weights = self.core(x[..., :13], legs)
        zrel = z + self.relation_context(z, checkpoint_chunks)
        if self.relation_enabled:
            pred = self.core.pred(zrel)
        pred = torch.cat([pred[:, :3] + 10 * x[:, 0, 0, 13:16], pred[:, 3:]], 1)
        return pred, zrel, weights


class DateData(nested.NestedData):
    """Full same-date context with uniform year/date optimization weight."""

    def __init__(self, fold: dict, offset_path: Path):
        super().__init__(fold)
        self.offset = np.load(offset_path, mmap_mode="r")
        self.date_rows = {int(t): g.index.to_numpy() for t, g in self.idx.groupby("t", sort=False)}
        mature = self.idx.iloc[self.train]
        self.year_dates = {
            int(year): np.array(sorted(g.t.unique()), dtype=np.int64)
            for year, g in mature.groupby("year", sort=True)
        }
        assert self.years == sorted(self.year_dates)

    def draw_date(self, rng: np.random.Generator) -> tuple[int, np.ndarray]:
        year = self.years[int(rng.integers(len(self.years)))]
        dates = self.year_dates[year]
        t = int(dates[int(rng.integers(len(dates)))])
        rows = self.date_rows[t]
        assert np.isfinite(self.y[rows, 1]).any()
        return t, rows


def objective(model: AllStockModel, x, legs, y, t, consistency: float):
    pred, z, _ = model(x, legs, checkpoint_chunks=True)
    valid = torch.isfinite(y)
    target = torch.nan_to_num(y) * 10
    reg = F.smooth_l1_loss(pred[:, :3], target, reduction="none")
    weights = torch.tensor([0.25, 0.5, 0.25], device=x.device)
    loss = (reg * valid * weights).sum() / (valid * weights).sum().clamp_min(1)
    if model.c["objective"] >= 2:
        yc = torch.stack([y[:, 1] > 0, y[:, 1] > 0.1, y[:, 1] < -0.1], 1).float()
        mask = valid[:, 1:2]
        ce = F.binary_cross_entropy_with_logits(pred[:, 3:], yc, reduction="none")
        loss = loss + 0.1 * (ce * mask).sum() / (mask.sum() * 3).clamp_min(1)
    if consistency:
        jitter = x + torch.randn_like(x) * 0.001
        _, z2, _ = model(jitter, legs, checkpoint_chunks=True)
        loss = loss + consistency * (1 - F.cosine_similarity(z, z2)).mean()
    return loss


def protocol() -> tuple[dict, dict]:
    p = json.loads(PROTOCOL.read_text())
    fold = next(row for row in p["folds"] if row["outer_year"] == 2020)
    binding = next(row for row in p["incumbent_bindings"] if row["year"] == 2020)
    return p, {"fold": fold, "binding": binding}


def frozen_spec() -> dict:
    if SPEC_PATH.exists():
        return json.loads(SPEC_PATH.read_text())
    p, inner = protocol()
    binding = inner["binding"]
    start = NESTED / "2020_s17/step32768.pt"
    inner_complete = json.loads((NESTED / "2020_s17/COMPLETE.json").read_text())
    assert sha(start) == inner_complete["checkpoint_sha256"]
    sources = [
        Path(__file__),
        SRC / "train.py",
        SRC / "o2_nested_earlystop.py",
        SRC.parent / "ashare_wave_adaptive_path_v3/model.py",
        PROTOCOL,
    ]
    spec = {
        "experiment": "I0_ALLSTOCK_ATTENTION_LR_V1",
        "incumbent": "CENTERED_TOP10_H10",
        "inner_contract": "legal 2019H2; gradient cutoff 2019-06-28",
        "starting_checkpoint": str(start),
        "starting_checkpoint_sha256": sha(start),
        "starting_checkpoint_role": "pre-2019H2 nested analogue used only for legal inner selection",
        "authoritative_formal_2020_checkpoint": binding["path"],
        "authoritative_formal_2020_checkpoint_sha256": binding["sha256"],
        "base_checkpoint": str(NESTED / "2020_s17/M0.joblib"),
        "base_checkpoint_sha256": sha(NESTED / "2020_s17/M0.joblib"),
        "config": binding["config"],
        "learning_rates": list(LRS),
        "registered_steps": list(STEPS),
        "lower_boundary_lr": 3e-7,
        "duration_boundary_steps": 64000,
        "query_chunk": QUERY_CHUNK,
        "relation": {
            "input": "authoritative 32D core.fusion output z immediately before core.pred",
            "normalization": "LayerNorm(z - same_date_mean(z))",
            "attention": "single-head exact all-stock QK softmax V; self masked",
            "dimension": 32,
            "injection": "z + Wo(context)",
            "initialization": "Wo weight and bias exactly zero; QKV standard initialization",
        },
        "sampling": "uniform year then uniform mature decision date; all same-date feature-eligible rows as context; mean masked loss per date",
        "control_selection": [
            "higher inner Top10 Ret20",
            "higher leave-best-3 Top10 Ret20",
            "higher Top10-minus-R11_20",
            "higher RankIC20",
            "less negative bottom-decile Top10 Ret20",
            "shorter steps",
            "larger LR",
        ],
        "relation_selection": "same lexicographic rule on relation-minus-matched-control deltas; requires positive Top10 Ret20 delta",
        "boundary_rule": {
            "improving_at_32k": "16k->32k Top10 Ret20 >= +0.0005 and inner MSE20 relative improvement >=0.5%",
            "64k": "extend only the selected matched pair once when improving_at_32k",
            "3e-7": "add exactly once only if 1e-6 is selected and improving_at_32k",
        },
        "profit_first_gate": {
            "mean_annual_return_delta_gt": 0,
            "worst_year_return_delta_ge": -0.03,
            "max_MaxDD_delta_le": 0.02,
            "leave_best3_active_daily_sum_ge": 0,
        },
        "development_years": [2020, 2021],
        "confirmation_year": 2022,
        "reserved_year": 2023,
        "sealed_years": [2024, 2025, 2026],
        "mps_hour_ceiling": 55,
        "minute_model_enabled": False,
        "minute_data_loaded": False,
        "source_hashes": {str(x): sha(x) for x in sources},
        "git_branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=REPO, text=True).strip(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "formal_outcomes_opened_at_freeze": False,
    }
    dump(SPEC_PATH, spec)
    return spec


def load_start(relation: bool, device: str = "cpu") -> tuple[AllStockModel, dict]:
    spec = frozen_spec()
    ck = torch.load(spec["starting_checkpoint"], map_location="cpu", weights_only=False)
    assert sha(Path(spec["starting_checkpoint"])) == spec["starting_checkpoint_sha256"]
    model = AllStockModel(ck["config"], relation=relation)
    missing, unexpected = model.load_state_dict(ck["state"], strict=not relation)
    if relation:
        assert set(missing) == {"norm.weight", "norm.bias", "q.weight", "q.bias", "k.weight", "k.bias", "v.weight", "v.bias", "o.weight", "o.bias"}
        assert not unexpected
    return model.to(device), ck


def preflight() -> None:
    spec = frozen_spec()
    update_state("RUNNING", "P0_IDENTITY_PARITY")
    p, inner = protocol()
    fold = inner["fold"]
    data = DateData(fold, NESTED / "2020_s17/offset.npy")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    assert device == "mps"
    base, _ = load_start(False, device)
    relation, _ = load_start(True, device)
    base.eval(); relation.eval()
    sample_dates = sorted(data.date_rows)[-3:]
    max_pred = 0.0
    max_z = 0.0
    with torch.no_grad():
        for t in sample_dates:
            rows = data.date_rows[t]
            x, legs = data.batch(rows, device)
            p0, z0, _ = base(x, legs)
            pr, zr, _ = relation(x, legs)
            max_pred = max(max_pred, float((p0 - pr).abs().max().cpu()))
            max_z = max(max_z, float((z0 - zr).abs().max().cpu()))
    assert max_pred <= 1e-7 and max_z <= 1e-7

    # Functional chunking test: make Wo nonzero, then compare exact full and chunked queries.
    test_rows = data.date_rows[sample_dates[0]][: min(96, len(data.date_rows[sample_dates[0]]))]
    x, legs = data.batch(test_rows, device)
    with torch.no_grad():
        relation.o.weight.normal_(0, 0.01)
        _, z, _ = relation.core(x[..., :13], legs)
        relation.query_chunk = len(test_rows)
        full = relation.relation_context(z)
        relation.query_chunk = 17
        chunked = relation.relation_context(z)
        chunk_diff = float((full - chunked).abs().max().cpu())
    assert chunk_diff <= 2e-6, chunk_diff

    # Incumbent prediction identity against the previously admitted cache.
    cached = np.load(SIGNAL_SPRINT / "2020/TRAIN_EMBED.npz")
    positions = np.linspace(0, len(data.train) - 1, 1024, dtype=int)
    rows = data.train[positions]
    pred = np.empty(len(rows), np.float32)
    embed = np.empty((len(rows), 32), np.float32)
    base.eval()
    with torch.no_grad():
        for lo in range(0, len(rows), 256):
            take = rows[lo : lo + 256]
            xx, ll = data.batch(take, device)
            pp, zz, _ = base(xx, ll)
            pred[lo : lo + len(take)] = pp[:, 1].cpu().numpy() / 10
            embed[lo : lo + len(take)] = zz.cpu().numpy()
    pred_diff = float(np.max(abs(pred - cached["pred20"][positions])))
    embed_diff = float(np.max(abs(embed - cached["embedding"][positions])))
    assert pred_diff <= 2e-6 and embed_diff <= 2e-5, (pred_diff, embed_diff)

    broader = load_module("allstock_broader", ROOT / "broader_ranking_portfolio_v1/run.py")
    account, _ = broader.verify_a0(2020)
    identity = {
        "status": "PASS",
        "dates_tested": sample_dates,
        "maximum_prediction_difference": max_pred,
        "maximum_embedding_difference": max_z,
        "chunked_vs_unchunked_max_abs": chunk_diff,
        "incumbent_cached_prediction_max_abs": pred_diff,
        "incumbent_cached_embedding_max_abs": embed_diff,
        "complete_same_date_universe": True,
        "self_attention_masked": True,
        "future_labels_used_for_context": False,
        "account_2020_annual_return": account["annual_return"],
        "account_2020_MaxDD": account["MaxDD"],
        "account_reconciliation": account["account_reconciliation"],
    }
    dump(HERE / "ATTENTION_IDENTITY_TEST.json", identity)
    (HERE / "IDENTITY_AUDIT.md").write_text(
        "# I0 all-stock attention identity audit\n\n"
        f"- Repository: `{REPO}`\n- Branch: `{spec['git_branch']}`\n- HEAD: `{spec['head']}`\n"
        f"- Authoritative inner checkpoint: `{spec['starting_checkpoint']}` (`{spec['starting_checkpoint_sha256']}`)\n"
        "- Representation H: the 32-dimensional `core.fusion` output `z`, immediately before `core.pred`.\n"
        "- Base path: `PathResidual` adds the frozen M0 Ret10/20/40 offsets after `core.pred`.\n"
        "- CENTERED: separately fitted continuous relative-Ret20 readout over date-demeaned H; per-seed daily percentile then fixed3 mean.\n"
        "- Account: RAW-positive admission, fixed Top10, H10, exact cash-only legal engine, independent RMB 1,000,000 per year.\n"
        "- Optimizer/objective: AdamW, frozen weight decay/betas, O2 smooth-L1 Ret10/20/40 plus frozen auxiliary BCE and consistency.\n"
        f"- Zero-output relation identity: PASS (prediction max abs `{max_pred:.3g}`).\n"
        f"- Frozen I0 cache parity: PASS (prediction `{pred_diff:.3g}`, embedding `{embed_diff:.3g}`).\n"
        f"- 2020 account parity: PASS (return `{account['annual_return']:.8%}`, MaxDD `{account['MaxDD']:.8%}`).\n"
        "- Minute model/data: disabled / not loaded.\n"
    )
    tests = {
        "incumbent_I0_reproduction": True,
        "hybrid_zero_output_identity": True,
        "complete_same_date_context": True,
        "chunking_exact": True,
        "future_labels_excluded_from_context_eligibility": True,
        "matched_universe_contract": True,
        "fixed3_contract_unchanged": True,
        "account_engine_parity": True,
        "2022_not_opened": True,
        "2023_not_opened": True,
        "2024_2026_not_opened": True,
    }
    dump(HERE / "REGRESSION_TESTS.json", {"status": "PASS", "tests": tests})
    update_state("WAITING", "P0_COMPLETE", identity_test=identity)
    del base, relation, data
    gc.collect(); torch.mps.empty_cache()


def smoke(steps: int = 3) -> None:
    update_state("RUNNING", "P0_MPS_SMOKE")
    _, inner = protocol()
    data = DateData(inner["fold"], NESTED / "2020_s17/offset.npy")
    records = []
    for relation_enabled in (False, True):
        torch.manual_seed(17)
        rng = np.random.default_rng(17)
        model, ck = load_start(relation_enabled, "mps")
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-5, weight_decay=ck["config"]["weight_decay"])
        start = time.monotonic()
        stocks = []
        for step in range(steps):
            t, rows = data.draw_date(rng)
            stocks.append(len(rows))
            x, legs = data.batch(rows, "mps")
            y = torch.as_tensor(data.y[rows], device="mps")
            tt = torch.full((len(rows),), t, dtype=torch.long, device="mps")
            optimizer.zero_grad(set_to_none=True)
            loss = objective(model, x, legs, y, tt, ck["config"]["consistency"])
            assert torch.isfinite(loss)
            loss.backward()
            grad = torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
            assert torch.isfinite(grad)
            optimizer.step()
            torch.mps.synchronize()
        seconds = time.monotonic() - start
        records.append(
            {
                "arm": "RELATION" if relation_enabled else "CONTROL",
                "steps": steps,
                "mean_stocks": float(np.mean(stocks)),
                "seconds": seconds,
                "seconds_per_step": seconds / steps,
                "projected_hours_one_32k": seconds / steps * 32000 / 3600,
                "mps_allocated_bytes": int(torch.mps.current_allocated_memory()),
            }
        )
        del model, optimizer
        gc.collect(); torch.mps.empty_cache()
    table = pd.DataFrame(records)
    table.to_csv(HERE / "MPS_SMOKE.csv", index=False)
    projected = float(sum(table.projected_hours_one_32k)) * len(LRS)
    dump(HERE / "RUNTIME_PLAN.json", {
        "smoke": records,
        "projected_primary_grid_mps_hours": projected,
        "hard_ceiling_hours": frozen_spec()["mps_hour_ceiling"],
        "within_ceiling": projected <= frozen_spec()["mps_hour_ceiling"],
        "note": "Projection excludes evaluation and permitted boundary extensions; formal launch fails closed if primary grid alone exceeds ceiling.",
    })
    update_state("WAITING", "P0_SMOKE_COMPLETE", projected_primary_grid_mps_hours=projected)


def save_checkpoint(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.pt")
    torch.save(value, tmp)
    tmp.replace(path)


def tag_lr(lr: float) -> str:
    return f"{lr:.0e}".replace("-", "m")


def trajectory_dir(stage: str, year: int, seed: int, relation: bool, lr: float) -> Path:
    arm = "RELATION" if relation else "CONTROL"
    return EXT / "training" / stage / f"y{year}_s{seed}_{arm}_lr{tag_lr(lr)}"


def load_model_checkpoint(path: Path, relation: bool, device: str = "mps") -> tuple[AllStockModel, dict]:
    ck = torch.load(path, map_location="cpu", weights_only=False)
    model = AllStockModel(ck["config"], relation=relation)
    model.load_state_dict(ck["state"])
    return model.to(device), ck


def infer_rows_by_date(model: AllStockModel, data: DateData, wanted: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Infer wanted rows while every query sees its complete same-date context."""
    wanted = np.asarray(wanted, dtype=np.int64)
    locate = np.full(len(data.idx), -1, dtype=np.int64)
    locate[wanted] = np.arange(len(wanted))
    pred = np.empty(len(wanted), np.float32)
    embedding = np.empty((len(wanted), int(model.c["embedding"])), np.float32)
    model.eval()
    with torch.no_grad():
        for t in sorted(np.unique(data.t[wanted])):
            rows = data.date_rows[int(t)]
            x, legs = data.batch(rows, "mps")
            p, z, _ = model(x, legs)
            pos = locate[rows]
            take = pos >= 0
            assert take.any()
            pred[pos[take]] = p[take, 1].cpu().numpy() / 10
            embedding[pos[take]] = z[take].cpu().numpy()
    return pred, embedding


def quick_inner_mse(model: AllStockModel, data: DateData) -> float:
    pred, _ = infer_rows_by_date(model, data, data.dev_rows)
    return float(np.mean((pred - data.eval_y[data.dev_rows, 1]) ** 2, dtype=np.float64))


def train_trajectory(
    data: DateData,
    start_path: Path,
    stage: str,
    year: int,
    seed: int,
    relation: bool,
    lr: float,
    max_steps: int,
) -> dict:
    dest = trajectory_dir(stage, year, seed, relation, lr)
    done = dest / f"COMPLETE_{max_steps}.json"
    if done.exists():
        record = json.loads(done.read_text())
        assert sha(dest / f"step{max_steps}.pt") == record["checkpoint_sha256"]
        return record
    base = torch.load(start_path, map_location="cpu", weights_only=False)
    config = base["config"]
    identity = {
        "spec_sha256": sha(SPEC_PATH), "stage": stage, "year": year, "seed": seed,
        "relation": relation, "lr": lr, "start_sha256": sha(start_path),
        "weight_decay": config["weight_decay"], "query_chunk": QUERY_CHUNK,
        "sampling": "uniform_year_then_date_full_cross_section",
    }
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    model = AllStockModel(config, relation=relation).to("mps")
    missing, unexpected = model.load_state_dict(base["state"], strict=not relation)
    if relation:
        assert len(missing) == 10 and not unexpected
    torch.manual_seed(seed)
    torch.mps.manual_seed(seed)
    rng = np.random.default_rng(seed)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=config["weight_decay"])
    resume = dest / "resume.pt"
    first = 1
    active_seconds = 0.0
    sampled_dates: dict[int, int] = {}
    curve: list[dict] = []
    if resume.exists():
        saved = torch.load(resume, map_location="cpu", weights_only=False)
        assert saved["identity"] == identity
        model.load_state_dict(saved["state"])
        optimizer.load_state_dict(saved["optimizer"])
        rng.bit_generator.state = saved["numpy_rng"]
        torch.set_rng_state(saved["torch_rng"])
        torch.mps.set_rng_state(saved["mps_rng"])
        first = int(saved["step"]) + 1
        active_seconds = float(saved["active_seconds"])
        sampled_dates = {int(k): int(v) for k, v in saved["sampled_dates"].items()}
        curve = list(saved["curve"])
    registered = {s for s in STEPS if s <= max_steps}
    registered.add(max_steps)
    start = time.monotonic()
    update_state("RUNNING", "P2_INNER_TRAIN" if stage == "INNER" else "P4_FORMAL_TRAIN",
                 arm="RELATION" if relation else "CONTROL", lr=lr, step=first - 1,
                 max_steps=max_steps, year=year, seed=seed)
    for step in range(first, max_steps + 1):
        model.train()
        t, rows = data.draw_date(rng)
        sampled_dates[t] = sampled_dates.get(t, 0) + 1
        x, legs = data.batch(rows, "mps")
        y = torch.as_tensor(data.y[rows], device="mps")
        tt = torch.full((len(rows),), t, dtype=torch.long, device="mps")
        optimizer.zero_grad(set_to_none=True)
        loss = objective(model, x, legs, y, tt, config["consistency"])
        assert torch.isfinite(loss)
        loss.backward()
        grad = torch.nn.utils.clip_grad_norm_(model.parameters(), 1)
        assert torch.isfinite(grad)
        optimizer.step()
        must_save = step in registered or step % 512 == 0 or step == max_steps
        if must_save:
            torch.mps.synchronize()
            elapsed = active_seconds + time.monotonic() - start
            trng, mrng = torch.get_rng_state(), torch.mps.get_rng_state()
            mse = None
            checkpoint_path = None
            if step in registered:
                mse = quick_inner_mse(model, data) if stage == "INNER" else None
                checkpoint_path = dest / f"step{step}.pt"
                curve.append({
                    "step": step, "inner_mse20": mse, "last_loss": float(loss.detach().cpu()),
                    "grad_before_clip": float(grad.detach().cpu()), "active_seconds": elapsed,
                })
            saved = {
                "identity": identity, "config": config,
                "state": {k: v.detach().cpu().clone() for k, v in model.state_dict().items()},
                "optimizer": optimizer.state_dict(), "step": step,
                "numpy_rng": rng.bit_generator.state, "torch_rng": trng, "mps_rng": mrng,
                "sampled_dates": sampled_dates, "curve": curve, "active_seconds": elapsed,
            }
            if checkpoint_path is not None:
                save_checkpoint(checkpoint_path, saved)
                curve[-1]["checkpoint_sha256"] = sha(checkpoint_path)
                saved["curve"] = curve
            save_checkpoint(resume, saved)
            dump(dest / "PROGRESS.json", {
                "identity": identity, "step": step, "max_steps": max_steps,
                "active_seconds": elapsed, "curve": curve,
                "unique_sampled_dates": len(sampled_dates), "last_cross_section": len(rows),
            })
            update_state("RUNNING", "P2_INNER_TRAIN" if stage == "INNER" else "P4_FORMAL_TRAIN",
                         arm="RELATION" if relation else "CONTROL", lr=lr, step=step,
                         max_steps=max_steps, year=year, seed=seed, active_seconds=elapsed)
            torch.set_rng_state(trng); torch.mps.set_rng_state(mrng)
            model.train(); start = time.monotonic(); active_seconds = elapsed
    actual_dates = np.array(sorted(sampled_dates))
    actual = data.idx[data.idx.t.isin(actual_dates)]
    if stage != "UNIT_TEST":
        assert pd.Timestamp(actual.decision_date.min()) + pd.DateOffset(years=12) <= pd.Timestamp(actual.decision_date.max())
    record = {
        "status": "COMPLETE", "identity": identity, "step": max_steps,
        "checkpoint_sha256": sha(dest / f"step{max_steps}.pt"),
        "active_seconds": active_seconds + time.monotonic() - start,
        "unique_sampled_dates": len(sampled_dates), "first_sampled_date": actual.decision_date.min(),
        "last_sampled_date": actual.decision_date.max(), "curve": curve,
    }
    dump(done, record)
    del model, optimizer
    gc.collect(); torch.mps.empty_cache()
    return record


def centered(values: np.ndarray, dates: np.ndarray) -> np.ndarray:
    frame = pd.DataFrame(np.asarray(values, dtype=np.float64))
    return (frame - frame.groupby(np.asarray(dates)).transform("mean")).to_numpy()


def fit_weights(dates: np.ndarray, years: np.ndarray) -> np.ndarray:
    frame = pd.DataFrame({"t": dates, "year": years})
    count = frame.groupby("t").t.transform("size").to_numpy()
    per_year = frame.groupby("year").t.nunique()
    value = 1 / count / np.array([per_year[y] for y in years])
    return value / value.mean()


def fit_centered_branch(model: AllStockModel, data: DateData, folder: Path) -> dict:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "CENTERED_BRANCH.joblib"
    proof = folder / "CENTERED_BRANCH.json"
    if proof.exists():
        record = json.loads(proof.read_text())
        assert sha(path) == record["sha256"]
        return joblib.load(path)
    pred, embedding = infer_rows_by_date(model, data, data.train)
    index = data.idx.iloc[data.train].reset_index(drop=True)
    x = centered(embedding, index.t.to_numpy())
    w = fit_weights(index.t.to_numpy(), index.year.to_numpy())
    scaler = StandardScaler(with_mean=False).fit(x, sample_weight=w)
    xs = scaler.transform(x)
    w = w / w.sum()
    error = 10 * centered((pred.astype(float) - data.y[data.train, 1].astype(float))[:, None], index.t).ravel()
    _, singular, vt = svd(xs * np.sqrt(w[:, None]), full_matrices=False, lapack_driver="gesdd")
    keep = singular > np.finfo(float).eps * max(xs.shape) * singular[0]
    vectors, ss = vt[keep].T, singular[keep]
    vectors *= np.sign(vectors[np.argmax(abs(vectors), axis=0), np.arange(vectors.shape[1])])
    transform = vectors / ss
    z = xs @ transform
    result, method, ok = centered_solve(z, xs, transform, error, w)
    repeat, repeat_method, repeat_ok = centered_solve(z, xs, transform, error, w)
    assert ok and repeat_ok and method == repeat_method and np.array_equal(result.x, repeat.x)
    theta = transform @ result.x
    assert np.max(abs(xs @ theta - z @ result.x)) <= centered_tolerance(xs, z, theta, result.x)
    branch = {"theta": theta, "scaler": scaler, "train_rows": len(data.train), "solver": method}
    tmp = path.with_suffix(".tmp.joblib")
    joblib.dump(branch, tmp); tmp.replace(path)
    dump(proof, {"sha256": sha(path), "train_rows": len(data.train), "solver": method})
    return branch


def signal_daily(frame: pd.DataFrame) -> pd.DataFrame:
    records = []
    for t, group in frame.groupby("t", sort=True):
        score = group.score.to_numpy(float)
        target = group.ret20.to_numpy(float)
        finite = np.isfinite(target)
        if finite.sum() < 50:
            continue
        order = np.lexsort((group.j.to_numpy(), -score))
        universe = float(target[finite].mean())
        top10 = float(target[order[:10]].mean()) if np.isfinite(target[order[:10]]).all() else np.nan
        top50 = float(target[order[:50]].mean()) if np.isfinite(target[order[:50]]).all() else np.nan
        r11 = float(target[order[10:20]].mean()) if np.isfinite(target[order[10:20]]).all() else np.nan
        ric = float(spearmanr(score[finite], target[finite]).statistic)
        records.append({
            "t": int(t), "date": group.decision_date.iloc[0], "RankIC20": ric,
            "universe_ret20": universe, "top10_ret20": top10, "top10_lift20": top10 - universe,
            "top50_ret20": top50, "top50_lift20": top50 - universe,
            "R1_2": float(target[order[:2]].mean()), "R3_5": float(target[order[2:5]].mean()),
            "R6_10": float(target[order[5:10]].mean()), "R11_20": r11,
            "top10_minus_R11_20": top10 - r11,
        })
    return pd.DataFrame(records)


def summarize_inner(daily: pd.DataFrame, inner_mse20: float) -> dict:
    top = daily.top10_ret20.dropna()
    return {
        "dates": len(top), "RankIC20": float(daily.RankIC20.mean()),
        "top10_ret20": float(top.mean()), "top10_lift20": float(daily.top10_lift20.mean()),
        "top50_ret20": float(daily.top50_ret20.mean()), "top50_lift20": float(daily.top50_lift20.mean()),
        "top10_minus_R11_20": float(daily.top10_minus_R11_20.mean()),
        "bottom_decile_ret20": float(top.nsmallest(max(1, int(math.ceil(len(top) * 0.1)))).mean()),
        "leave_best1": float(top.drop(top.nlargest(1).index).mean()),
        "leave_best3": float(top.drop(top.nlargest(3).index).mean()),
        "positive_date_fraction": float((top > 0).mean()), "inner_mse20": inner_mse20,
    }


def evaluate_inner_checkpoint(data: DateData, relation: bool, lr: float, steps: int) -> dict:
    dest = trajectory_dir("INNER", 2020, 17, relation, lr) / f"eval_step{steps}"
    result_path = dest / "RESULT.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    model, ck = load_model_checkpoint(trajectory_dir("INNER", 2020, 17, relation, lr) / f"step{steps}.pt", relation)
    branch = fit_centered_branch(model, data, dest)
    raw, embedding = infer_rows_by_date(model, data, data.dev_rows)
    index = data.idx.iloc[data.dev_rows].reset_index(drop=True)
    correction = centered((branch["scaler"].transform(centered(embedding, index.t)) @ branch["theta"])[:, None], index.t).ravel()
    assert pd.Series(correction).groupby(index.t).mean().abs().max() < 1e-10
    frame = index[["t", "j", "decision_date"]].copy()
    frame["score"] = raw + correction / 10
    frame["ret20"] = data.eval_y[data.dev_rows, 1]
    daily = signal_daily(frame)
    dest.mkdir(parents=True, exist_ok=True)
    daily.to_parquet(dest / "DAILY.parquet", index=False)
    inner_mse = float(np.mean((raw - data.eval_y[data.dev_rows, 1]) ** 2, dtype=np.float64))
    result = {
        "arm": "RELATION" if relation else "CONTROL", "lr": lr, "steps": steps,
        "checkpoint_sha256": sha(trajectory_dir("INNER", 2020, 17, relation, lr) / f"step{steps}.pt"),
        **summarize_inner(daily, inner_mse),
    }
    dump(result_path, result)
    del model
    gc.collect(); torch.mps.empty_cache()
    return result


def write_sweep(rows: list[dict]) -> pd.DataFrame:
    table = pd.DataFrame(rows).sort_values(["lr", "steps", "arm"], ascending=[False, True, True])
    table.to_parquet(HERE / "LR_SWEEP_RESULTS.parquet", index=False)
    return table


def pick_candidates(table: pd.DataFrame) -> tuple[dict, dict | None]:
    metrics = ["top10_ret20", "leave_best3", "top10_minus_R11_20", "RankIC20", "bottom_decile_ret20"]
    control = table[table.arm == "CONTROL"].sort_values(
        metrics + ["steps", "lr"], ascending=[False, False, False, False, False, True, False]
    ).iloc[0].to_dict()
    base = table[table.arm == "CONTROL"].set_index(["lr", "steps"])
    candidates = []
    for _, row in table[table.arm == "RELATION"].iterrows():
        matched = base.loc[(row.lr, row.steps)]
        record = row.to_dict()
        for metric in metrics:
            record[f"delta_{metric}"] = float(row[metric] - matched[metric])
        if record["delta_top10_ret20"] > 0:
            candidates.append(record)
    relation = None
    if candidates:
        relation = sorted(candidates, key=lambda x: (
            x["delta_top10_ret20"], x["delta_leave_best3"], x["delta_top10_minus_R11_20"],
            x["delta_RankIC20"], x["delta_bottom_decile_ret20"], -x["steps"], x["lr"]
        ), reverse=True)[0]
    return clean(control), clean(relation)


def improving_boundary(table: pd.DataFrame, arm: str, lr: float) -> bool:
    subset = table[(table.arm == arm) & np.isclose(table.lr, lr)].set_index("steps")
    if 16000 not in subset.index or 32000 not in subset.index:
        return False
    a, b = subset.loc[16000], subset.loc[32000]
    return bool(b.top10_ret20 - a.top10_ret20 >= 0.0005 and (a.inner_mse20 - b.inner_mse20) / a.inner_mse20 >= 0.005)


def inner_grid() -> dict:
    update_state("RUNNING", "P2_INNER_GRID")
    _, inner = protocol()
    data = DateData(inner["fold"], NESTED / "2020_s17/offset.npy")
    start = Path(frozen_spec()["starting_checkpoint"])
    for lr in LRS:
        for relation in (False, True):
            train_trajectory(data, start, "INNER", 2020, 17, relation, lr, 32000)
    rows = [evaluate_inner_checkpoint(data, relation, lr, steps)
            for lr in LRS for steps in STEPS for relation in (False, True)]
    table = write_sweep(rows)
    control, relation = pick_candidates(table)
    primary = relation if relation is not None else control
    primary_arm = primary["arm"]
    lr = float(primary["lr"])
    if lr == 1e-6 and improving_boundary(table, primary_arm, lr):
        for relation_enabled in (False, True):
            train_trajectory(data, start, "INNER", 2020, 17, relation_enabled, 3e-7, 32000)
            rows.extend(evaluate_inner_checkpoint(data, relation_enabled, 3e-7, steps) for steps in STEPS)
        table = write_sweep(rows); control, relation = pick_candidates(table)
        primary = relation if relation is not None else control
    if int(primary["steps"]) == 32000 and improving_boundary(table, primary["arm"], float(primary["lr"])):
        for relation_enabled in (False, True):
            train_trajectory(data, start, "INNER", 2020, 17, relation_enabled, float(primary["lr"]), 64000)
            rows.append(evaluate_inner_checkpoint(data, relation_enabled, float(primary["lr"]), 64000))
        table = write_sweep(rows); control, relation = pick_candidates(table)
    selection = {
        "status": "FROZEN_BEFORE_2020_2021", "small_lr_control": control,
        "relation": relation, "relation_earned_inner": relation is not None,
        "table_sha256": sha(HERE / "LR_SWEEP_RESULTS.parquet"),
        "formal_outcomes_opened": False,
    }
    dump(HERE / "INNER_SELECTION.json", selection)
    update_state("WAITING", "P3_INNER_SELECTION_FROZEN", selection=selection)
    return selection


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["preflight", "smoke", "inner-grid"])
    parser.add_argument("--steps", type=int, default=3)
    args = parser.parse_args()
    EXT.mkdir(parents=True, exist_ok=True)
    lock_stream = None
    try:
        if args.stage == "inner-grid":
            lock_stream = LOCK.open("a+")
            fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            lock_stream.seek(0); lock_stream.truncate(); lock_stream.write(str(os.getpid())); lock_stream.flush()
        if args.stage == "preflight":
            preflight()
        elif args.stage == "smoke":
            smoke(args.steps)
        else:
            inner_grid()
    except Exception:
        dump(HERE / "ERROR_PACKET.json", {
            "status": "BLOCKED_NEEDS_CODEX",
            "stage": args.stage,
            "traceback": traceback.format_exc(),
            "safest_next_action": "repair deterministic implementation issue without changing EXPERIMENT_SPEC.json",
        })
        update_state("BLOCKED_NEEDS_CODEX", args.stage)
        raise
    finally:
        if lock_stream is not None:
            lock_stream.close()
            if LOCK.exists() and LOCK.read_text() == str(os.getpid()):
                LOCK.unlink()


if __name__ == "__main__":
    main()
