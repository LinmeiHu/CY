"""Qlib Alpha158 formula contract and a small exact-on-panel batch builder.

The builder is intentionally for P0 audits/benchmarks. A full-history cache is
not materialized unless the 72-hour run-budget gate permits training.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

WINDOWS = (5, 10, 20, 30, 60)
OPS = ("ROC", "MA", "STD", "BETA", "RSQR", "RESI", "MAX", "MIN", "QTLU", "QTLD",
       "RANK", "RSV", "IMAX", "IMIN", "IMXD", "CORR", "CORD", "CNTP", "CNTN",
       "CNTD", "SUMP", "SUMN", "SUMD", "VMA", "VSTD", "WVMA", "VSUMP", "VSUMN", "VSUMD")


def feature_contract() -> list[dict]:
    rows = [
        ("KMID", "(close-open)/open"), ("KLEN", "(high-low)/open"),
        ("KMID2", "(close-open)/(high-low+1e-12)"),
        ("KUP", "(high-max(open,close))/open"),
        ("KUP2", "(high-max(open,close))/(high-low+1e-12)"),
        ("KLOW", "(min(open,close)-low)/open"),
        ("KLOW2", "(min(open,close)-low)/(high-low+1e-12)"),
        ("KSFT", "(2*close-high-low)/open"),
        ("KSFT2", "(2*close-high-low)/(high-low+1e-12)"),
        ("OPEN0", "open/close"), ("HIGH0", "high/close"),
        ("LOW0", "low/close"), ("VWAP0", "vwap/close"),
    ]
    templates = {
        "ROC": "Ref(close,w)/close", "MA": "Mean(close,w)/close", "STD": "Std(close,w)/close",
        "BETA": "Slope(close,w)/close", "RSQR": "Rsquare(close,w)", "RESI": "Resi(close,w)/close",
        "MAX": "Max(high,w)/close", "MIN": "Min(low,w)/close", "QTLU": "Quantile(close,w,.8)/close",
        "QTLD": "Quantile(close,w,.2)/close", "RANK": "Rank(close,w)",
        "RSV": "(close-Min(low,w))/(Max(high,w)-Min(low,w)+1e-12)",
        "IMAX": "IdxMax(high,w)/w", "IMIN": "IdxMin(low,w)/w", "IMXD": "(IdxMax(high,w)-IdxMin(low,w))/w",
        "CORR": "Corr(close,Log(volume+1),w)",
        "CORD": "Corr(close/Ref(close,1),Log(volume/Ref(volume,1)+1),w)",
        "CNTP": "Mean(close>Ref(close,1),w)", "CNTN": "Mean(close<Ref(close,1),w)",
        "CNTD": "CNTP-CNTN", "SUMP": "Sum(max(close-Ref(close,1),0),w)/Sum(abs(delta_close),w)",
        "SUMN": "Sum(max(Ref(close,1)-close,0),w)/Sum(abs(delta_close),w)", "SUMD": "SUMP-SUMN",
        "VMA": "Mean(volume,w)/volume", "VSTD": "Std(volume,w)/volume",
        "WVMA": "Std(abs(close/Ref(close,1)-1)*volume,w)/Mean(abs(close/Ref(close,1)-1)*volume,w)",
        "VSUMP": "Sum(max(volume-Ref(volume,1),0),w)/Sum(abs(delta_volume),w)",
        "VSUMN": "Sum(max(Ref(volume,1)-volume,0),w)/Sum(abs(delta_volume),w)", "VSUMD": "VSUMP-VSUMN",
    }
    for op in OPS:
        rows.extend((f"{op}{w}", templates[op].replace("w", str(w))) for w in WINDOWS)
    assert len(rows) == 158
    return [{"index": i, "name": n, "formula": f, "available_at": "decision-date close"} for i, (n, f) in enumerate(rows)]


def _nan_corr(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ok = np.isfinite(a) & np.isfinite(b); n = ok.sum(0)
    aa = np.where(ok, a, 0.0); bb = np.where(ok, b, 0.0)
    ma = aa.sum(0) / np.maximum(n, 1); mb = bb.sum(0) / np.maximum(n, 1)
    da = np.where(ok, a - ma, 0.0); db = np.where(ok, b - mb, 0.0)
    den = np.sqrt((da * da).sum(0) * (db * db).sum(0))
    return np.where((n >= 2) & (den > 0), (da * db).sum(0) / den, np.nan)


def _regression(y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.arange(1, y.shape[0] + 1, dtype=float)[:, None]
    ok = np.isfinite(y); n = ok.sum(0); yy = np.where(ok, y, 0.0); xx = np.where(ok, x, 0.0)
    sx, sy = xx.sum(0), yy.sum(0); sxx = (xx * xx).sum(0); sxy = (xx * yy).sum(0)
    den = n * sxx - sx * sx
    slope = np.where((n >= 2) & (den != 0), (n * sxy - sx * sy) / den, np.nan)
    intercept = np.where(n > 0, (sy - slope * sx) / np.maximum(n, 1), np.nan)
    pred = intercept + slope * x
    resid = y - pred
    ssr = np.nansum(resid * resid, axis=0)
    mean = sy / np.maximum(n, 1); sst = np.nansum(np.where(ok, y - mean, np.nan) ** 2, axis=0)
    rsq = np.where((n >= 2) & (sst > 0), 1.0 - ssr / sst, np.nan)
    return slope, rsq, resid[-1]


class PanelAlpha158:
    def __init__(self, panel: Path):
        self.panel = panel
        self.axes = json.loads((panel / "axes.json").read_text())
        self.dates = np.asarray(self.axes["dates"])
        self.hard = np.load(panel / "hard_valid.npy", mmap_mode="r")
        self.history = np.load(panel / "history.npy", mmap_mode="r")
        self.open = np.load(panel / "adj_open.npy", mmap_mode="r")
        self.high = np.load(panel / "adj_high.npy", mmap_mode="r")
        self.low = np.load(panel / "adj_low.npy", mmap_mode="r")
        self.close = np.load(panel / "adj_close.npy", mmap_mode="r")
        self.volume = np.load(panel / "adj_volume.npy", mmap_mode="r")
        self.amount = np.load(panel / "amount.npy", mmap_mode="r")
        self.raw_volume = np.load(panel / "volume.npy", mmap_mode="r")
        self.raw_close = np.load(panel / "close.npy", mmap_mode="r")

    def universe(self, t: int) -> np.ndarray:
        # Exact parity with the authoritative full-forward rows in 2020/2021.
        return np.flatnonzero(self.hard[t] & (self.history[t] >= 60))

    def _snapshot(self, t: int, stocks: np.ndarray) -> np.ndarray:
        start = max(0, t - 60)
        o = np.asarray(self.open[start : t + 1, stocks], float)
        h = np.asarray(self.high[start : t + 1, stocks], float)
        l = np.asarray(self.low[start : t + 1, stocks], float)
        c = np.asarray(self.close[start : t + 1, stocks], float)
        v = np.asarray(self.volume[start : t + 1, stocks], float)
        a = np.asarray(self.amount[start : t + 1, stocks], float)
        eps = 1e-12; co, hi, lo, cl, vo = o[-1], h[-1], l[-1], c[-1], v[-1]
        # Adjusted VWAP must use adjusted volume. amount/raw_volume is raw VWAP.
        # Raw amount/raw volume is the source VWAP. Convert it into the same
        # adjusted-price coordinate as close; panel adj_volume is not exactly
        # the reciprocal price factor and therefore is not used for VWAP.
        raw_volume = np.asarray(self.raw_volume[t, stocks], float)
        raw_close = np.asarray(self.raw_close[t, stocks], float)
        vw = a[-1] / (raw_volume + eps) * cl / (raw_close + eps)
        cols = [(cl - co) / co, (hi - lo) / co, (cl - co) / (hi - lo + eps),
                (hi - np.maximum(co, cl)) / co, (hi - np.maximum(co, cl)) / (hi - lo + eps),
                (np.minimum(co, cl) - lo) / co, (np.minimum(co, cl) - lo) / (hi - lo + eps),
                (2 * cl - hi - lo) / co, (2 * cl - hi - lo) / (hi - lo + eps),
                co / cl, hi / cl, lo / cl, vw / cl]
        for op in OPS:
            for w in WINDOWS:
                cw, hw, lw, vw0 = c[-w:], h[-w:], l[-w:], v[-w:]
                change_window = min(w, len(c) - 1)
                dc = c[-change_window:] - c[-change_window-1:-1]
                dv = v[-change_window:] - v[-change_window-1:-1]
                if op == "ROC": z = c[-w-1] / cl if len(c) > w else np.full_like(cl, np.nan)
                elif op == "MA": z = np.nanmean(cw, 0) / cl
                elif op == "STD": z = np.nanstd(cw, 0, ddof=1) / cl
                elif op in ("BETA", "RSQR", "RESI"):
                    slope, rsq, resi = _regression(cw); z = {"BETA": slope / cl, "RSQR": rsq, "RESI": resi / cl}[op]
                elif op == "MAX": z = np.nanmax(hw, 0) / cl
                elif op == "MIN": z = np.nanmin(lw, 0) / cl
                elif op == "QTLU": z = np.nanquantile(cw, .8, axis=0) / cl
                elif op == "QTLD": z = np.nanquantile(cw, .2, axis=0) / cl
                elif op == "RANK":
                    less = np.sum(cw < cl, 0); equal = np.sum(cw == cl, 0); n = np.isfinite(cw).sum(0)
                    z = (less + (equal + 1) / 2) / np.maximum(n, 1)
                elif op == "RSV": z = (cl - np.nanmin(lw, 0)) / (np.nanmax(hw, 0) - np.nanmin(lw, 0) + eps)
                elif op == "IMAX": z = (np.nanargmax(np.where(np.isfinite(hw), hw, -np.inf), axis=0) + 1) / w
                elif op == "IMIN": z = (np.nanargmin(np.where(np.isfinite(lw), lw, np.inf), axis=0) + 1) / w
                elif op == "IMXD":
                    z = ((np.nanargmax(np.where(np.isfinite(hw), hw, -np.inf), axis=0) + 1) -
                         (np.nanargmin(np.where(np.isfinite(lw), lw, np.inf), axis=0) + 1)) / w
                elif op == "CORR": z = _nan_corr(cw, np.log(vw0 + 1))
                elif op == "CORD":
                    cr = c[-change_window:] / np.where(c[-change_window-1:-1] != 0, c[-change_window-1:-1], np.nan)
                    vr = np.log(v[-change_window:] / np.where(v[-change_window-1:-1] != 0, v[-change_window-1:-1], np.nan) + 1)
                    z = _nan_corr(cr, vr)
                elif op == "CNTP": z = np.nanmean(dc > 0, 0)
                elif op == "CNTN": z = np.nanmean(dc < 0, 0)
                elif op == "CNTD": z = np.nanmean(dc > 0, 0) - np.nanmean(dc < 0, 0)
                elif op in ("SUMP", "SUMN", "SUMD"):
                    den = np.nansum(np.abs(dc), 0) + eps; up = np.nansum(np.maximum(dc, 0), 0); dn = np.nansum(np.maximum(-dc, 0), 0)
                    z = {"SUMP": up / den, "SUMN": dn / den, "SUMD": (up - dn) / den}[op]
                elif op == "VMA": z = np.nanmean(vw0, 0) / (vo + eps)
                elif op == "VSTD": z = np.nanstd(vw0, 0, ddof=1) / (vo + eps)
                elif op == "WVMA":
                    cr = np.abs(c[-change_window:] / np.where(c[-change_window-1:-1] != 0, c[-change_window-1:-1], np.nan) - 1) * v[-change_window:]
                    z = np.nanstd(cr, 0, ddof=1) / (np.nanmean(cr, 0) + eps)
                else:
                    den = np.nansum(np.abs(dv), 0) + eps; up = np.nansum(np.maximum(dv, 0), 0); dn = np.nansum(np.maximum(-dv, 0), 0)
                    z = {"VSUMP": up / den, "VSUMN": dn / den, "VSUMD": (up - dn) / den}[op]
                cols.append(z)
        out = np.column_stack(cols).astype(np.float32)
        assert out.shape == (len(stocks), 158)
        return out

    def sequence(self, t: int) -> tuple[np.ndarray, np.ndarray]:
        stocks = self.universe(t)
        x = np.stack([self._snapshot(day, stocks) for day in range(t - 7, t + 1)], axis=1)
        return stocks, x
