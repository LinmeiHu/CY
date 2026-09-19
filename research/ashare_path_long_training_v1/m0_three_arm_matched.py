"""Isolated pre-2020 matched O2 experiment; never writes frozen Alpha assets."""
import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import joblib
import numpy as np
import pandas as pd
import torch
from torch import nn
from torch.nn import functional as F
import common

HERE = Path(__file__).resolve().parent
ROOT = common.OUT
DOC = HERE / 'account_diversification_v1/m0_three_arm_matched_v1'
OUT = ROOT / 'account_diversification_v1/m0_three_arm_matched_v1'
ARCH = ROOT / 'code_snapshots/7e2fd2a419a095d8abfdb8992230ef265b3612ffa5bfcca9873f6d334e107432_model.py'
BASE = ROOT / 'M1_OFFSET_2020_s17_O2_B32768.pt'
M0 = ROOT / 'M0_CONTEXT_2020.joblib'
ARMS = ['A_RESIDUAL', 'B_DIRECT', 'C_M0_FEATURE']
SEEDS = [17, 29, 43]


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2, default=str) + '\n')
    tmp.replace(path)


def sha(path):
    with open(path, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def source():
    assert sha(ARCH) == ARCH.name.split('_')[0]
    prior = sys.modules['common']
    sys.modules['common'] = common.old('common')
    try:
        spec = importlib.util.spec_from_file_location('matched_m0_archived_model', ARCH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.modules['common'] = prior


CODE = source()


class Model(nn.Module):
    def __init__(self, config, arm):
        super().__init__()
        self.c, self.arm, self.conditioned = config, arm, False
        self.core = CODE.PathModel(config)
        with torch.no_grad():
            self.core.pred.weight[:3].zero_()
            self.core.pred.bias[:3].zero_()
        if arm == 'C_M0_FEATURE':
            # Exactly a concatenated [embedding; raw M0 returns] affine head.
            # Zero extra columns preserve all common initial outputs and RNG.
            self.m0_weight = nn.Parameter(torch.zeros(6, 3))

    def forward(self, x, legs):
        p, z, w = self.core(x[..., :13], legs)
        m0 = x[:, 0, 0, 13:16]
        if self.arm == 'A_RESIDUAL':
            p = torch.cat([p[:, :3] + 10 * m0, p[:, 3:]], 1)
        elif self.arm == 'C_M0_FEATURE':
            p = p + F.linear(m0, self.m0_weight)
        return p, z, w


class Data:
    def __init__(self):
        manifest = json.loads((HERE / 'FEATURES.json').read_text())
        registry = json.loads((HERE / 'RESEARCH_REGISTRY.json').read_text())
        asset = next(a for a in registry['assets'] if a['asset_id'] == 'CY-WAVE-LONG-TRAINING-2007-2023')
        assert asset['lineage']['manifest_sha256'] == sha(HERE / 'FEATURES.json')
        assert manifest['split_sha256'] == sha(HERE / 'TIME_SPLIT.json')
        # Read index/date metadata, then select BEFORE reading any feature/label payload.
        idx = pd.read_parquet(ROOT / 'index.parquet')
        dates = np.array(json.loads((ROOT / 'panel/axes.json').read_text())['dates'])
        self.cut = int(np.flatnonzero(dates < '2020-01-01')[-1])
        keep = np.flatnonzero(idx.t.to_numpy() <= self.cut)
        self.original_rows = keep
        self.idx = idx.iloc[keep].reset_index(drop=True)
        self.t = self.idx.t.to_numpy()
        labels = np.load(ROOT / 'labels.npy', mmap_mode='r')
        self.y = np.full((len(keep), 3), np.nan, np.float32)
        for k, h in enumerate([10, 20, 40]):
            mature = self.t + 1 + h <= self.cut
            self.y[mature, k] = labels[keep[mature], k]
        self.train = np.flatnonzero(np.isfinite(self.y[:, 1]))
        self.groups = {int(y): [g.index.to_numpy() for _, g in z.groupby('t')]
                       for y, z in self.idx.iloc[self.train].groupby('year')}
        self.years = sorted(self.groups)
        first = pd.Timestamp(self.idx.iloc[self.train].decision_date.min())
        last = pd.Timestamp(self.idx.iloc[self.train].decision_date.max())
        assert first + pd.DateOffset(years=12) <= last
        assert self.years == list(range(first.year, last.year + 1))
        self.raw = np.load(ROOT / 'raw.npy', mmap_mode='r')
        self.legs = np.load(ROOT / 'legs.npy', mmap_mode='r')
        self.offset = np.load(ROOT / 'M0_CONTEXT_2020_offset.npy', mmap_mode='r')
        assert sha(M0) == '9a78ea8dadbf268ec22603b5789f171950fea593266c89ebde00d70cdc832b9c'
        frozen = joblib.load(M0)
        assert frozen['cutoff'] == str(dates[self.cut])
        assert frozen['feature_sha256'] == sha(HERE / 'FEATURES.json')
        probe = keep[np.linspace(0, len(keep)-1, 64).astype(int)]
        factors = np.load(ROOT / 'factors.npy', mmap_mode='r')
        xx = frozen['scale'].transform(np.nan_to_num(factors[probe]).astype('float64'))
        expected = np.column_stack([f.predict(xx) for f in frozen['fits']]).astype('float32')
        np.testing.assert_allclose(expected, self.offset[probe], atol=1e-7, rtol=1e-6)
        self.audit = dict(cutoff=str(dates[self.cut]), first_supervised=str(first.date()),
                          last_supervised=str(last.date()), effective_years=(last-first).days/365.2425,
                          mature_ret20=len(self.train), rows=len(keep), anniversary_gate=True,
                          yearly=self.idx.iloc[self.train].groupby('year').size().to_dict(),
                          new_post2019_payload_access=False, alpha_layer_oos=False,
                          labels_prefix_sha256=hashlib.sha256(self.y.tobytes()).hexdigest(),
                          index_prefix_sha256=hashlib.sha256(self.idx.to_json().encode()).hexdigest(),
                          data_integrity_scope='Registry identity, frozen M0 parity and exact pre2020 payload fingerprints; sealed future payloads not hashed/read')

    def draw(self, rng):
        return np.concatenate([rng.choice((g := self.groups[self.years[int(rng.integers(len(self.years)))]])[int(rng.integers(len(g)))], 16, replace=True) for _ in range(16)])

    def batch(self, rows, device):
        original = self.original_rows[rows]
        x = np.array(self.raw[original], np.float32)
        x = np.concatenate([x, np.broadcast_to(self.offset[original, None, None, :], (len(rows), 4, 32, 3))], -1)
        return torch.tensor(x, device=device), torch.tensor(np.array(self.legs[original], np.float32), device=device)


def preflight(data, config):
    models = []
    for arm in ARMS:
        torch.manual_seed(17)
        models.append(Model(config, arm).eval())
    for name, p in models[0].core.state_dict().items():
        for m in models[1:]:
            assert torch.equal(p, m.core.state_dict()[name]), name
    probe_rows = data.train[np.linspace(0, len(data.train)-1, 64).astype(int)]
    x, l = data.batch(probe_rows, 'cpu')
    with torch.no_grad():
        a, b, c = [m(x, l)[0] for m in models]
        torch.testing.assert_close(a[:, :3] - 10*x[:, 0, 0, 13:16], b[:, :3])
        torch.testing.assert_close(b, c)
    # Check actual frozen A inference against its saved pre2020 predictions.
    saved = torch.load(BASE, map_location='cpu', weights_only=False)
    assert saved['feature_sha256'] == sha(HERE / 'FEATURES.json')
    models[0].load_state_dict(saved['state'], strict=True)
    prior = pd.read_parquet(ROOT / 'M1_OFFSET_2020_s17_O2_B32768_TRAIN_FITTED_DIAGNOSTIC_ONLY_pred.parquet')
    assert np.array_equal(prior[['t', 'j']].to_numpy(), data.idx[['t', 'j']].to_numpy())
    with torch.no_grad():
        pred = models[0](x, l)[0][:, :3].numpy()/10
    expected = prior.iloc[probe_rows][['pred10', 'pred20', 'pred40']].to_numpy()
    np.testing.assert_allclose(pred, expected, atol=3e-5, rtol=3e-5)
    for model in models[1:]:
        model.train()
        loss = CODE.objective(model, x, l, torch.tensor(data.y[probe_rows]),
                              torch.tensor(data.t[probe_rows]), config['consistency'])
        loss.backward()
        assert torch.isfinite(loss)
        assert all(torch.isfinite(p.grad).all() for p in model.parameters() if p.grad is not None)
        if model.arm == 'C_M0_FEATURE':
            assert model.m0_weight.grad.abs().sum() > 0
    result = dict(at=stamp(), **data.audit, common_initial_weights_equal=True,
                  frozen_residual_prediction_max_error=float(np.max(np.abs(pred-expected))),
                  m0_extra_head_zero_init=True, finite_backward_checks=True,
                  frozen_prediction_support_exact=True, sampler_identical_by_construction=True)
    write(DOC / 'PREFLIGHT.json', result)
    return result


def evaluate(model, data, folder, device):
    model.eval()
    chunks = []
    with torch.no_grad():
        for start in range(0, len(data.idx), 1024):
            x, l = data.batch(np.arange(start, min(start+1024, len(data.idx))), device)
            p = model(x, l)[0].cpu().numpy()
            p[:, :3] /= 10
            chunks.append(p)
    pred = np.concatenate(chunks)
    np.save(folder / 'TRAIN_PREDICTIONS.npy', pred)
    daily = []
    for t, g in data.idx.groupby('t'):
        ii = g.index.to_numpy(); p = pred[ii, 1]; y = data.y[ii, 1]
        ok = np.isfinite(y)
        if not ok.any():
            continue
        rank = np.lexsort((g.j.to_numpy(), -p))
        row = dict(date=g.decision_date.iloc[0], year=int(g.year.iloc[0]), n=len(g), valid=int(ok.sum()),
                   mse20=float(np.mean((p[ok]-y[ok])**2)),
                   global_ic=pd.Series(p[ok]).corr(pd.Series(y[ok]), method='spearman'),
                   universe_mean=float(np.mean(y[ok])))
        for k in [10, 50]:
            yy = y[rank[:k]]; valid = np.isfinite(yy)
            row.update({f'top{k}_ret20': float(np.mean(yy[valid])) if valid.any() else None,
                        f'top{k}_coverage': float(valid.mean()),
                        f'top{k}_positive': float((yy[valid]>0).mean()) if valid.any() else None,
                        f'top{k}_down10': float((yy[valid]<-.1).mean()) if valid.any() else None})
        daily.append(row)
    frame = pd.DataFrame(daily)
    frame.to_parquet(folder / 'TRAIN_DAILY_METRICS.parquet', index=False)
    frame.groupby('year').mean(numeric_only=True).to_csv(folder / 'TRAIN_YEARLY_METRICS.csv')


def train(data, config, arm, seed, spec_hash):
    folder = OUT / f'{arm}_s{seed}'; folder.mkdir(parents=True, exist_ok=True)
    if (folder / 'COMPLETE.json').exists():
        assert json.loads((folder/'COMPLETE.json').read_text())['spec_sha256'] == spec_hash
        return
    device = 'mps' if torch.backends.mps.is_available() else 'cpu'
    torch.manual_seed(seed); rng = np.random.default_rng(seed)
    m = Model(config, arm).to(device)
    opt = torch.optim.AdamW(m.parameters(), lr=config['lr'], weight_decay=config['weight_decay'])
    start = 0; draws = np.zeros(len(data.idx), np.int64)
    last = folder / 'LAST.pt'
    if last.exists():
        s = torch.load(last, map_location='cpu', weights_only=False)
        assert s['spec_sha256'] == spec_hash
        m.load_state_dict(s['state']); opt.load_state_dict(s['optimizer'])
        start = s['step']; draws = s['draws']; rng.bit_generator.state = s['numpy_rng']
        torch.set_rng_state(s['torch_rng'])
        if device == 'mps': torch.mps.set_rng_state(s['mps_rng'])
    y = torch.tensor(data.y, device=device); t = torch.tensor(data.t, device=device)
    for step in range(start+1, 32769):
        m.train(); rows = data.draw(rng); np.add.at(draws, rows, 1)
        x, l = data.batch(rows, device)
        opt.zero_grad(set_to_none=True)
        loss = CODE.objective(m, x, l, y[rows], t[rows], config['consistency'])
        assert torch.isfinite(loss), (arm, seed, step)
        loss.backward(); nn.utils.clip_grad_norm_(m.parameters(), 1); opt.step()
        if step == 1 or step % 500 == 0 or step in [8192, 16384, 32768]:
            state = dict(config=config, arm=arm, seed=seed, step=step, state=m.state_dict(),
                         optimizer=opt.state_dict(), numpy_rng=rng.bit_generator.state,
                         torch_rng=torch.get_rng_state(), mps_rng=torch.mps.get_rng_state() if device=='mps' else None,
                         draws=draws, spec_sha256=spec_hash, cutoff=data.audit['cutoff'])
            tmp = folder / 'LAST.tmp'; torch.save(state, tmp); tmp.replace(last)
            if step in [8192, 16384, 32768]:
                torch.save(state, folder / f'B{step}.pt')
            write(folder/'PROGRESS.json', dict(at=stamp(), step=step, loss=float(loss), pid=os.getpid()))
            print(stamp(), arm, seed, step, float(loss), flush=True)
    evaluate(m, data, folder, device)
    write(folder/'COMPLETE.json', dict(at=stamp(), spec_sha256=spec_hash, step=32768,
          draws=int(draws.sum()), unique=int((draws>0).sum()), sampler_state=rng.bit_generator.state,
          draw_counts_sha256=hashlib.sha256(draws.tobytes()).hexdigest(), scope='TRAIN_FITTED_DIAGNOSTIC_ONLY'))
    del m, opt
    if device == 'mps': torch.mps.empty_cache()


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--run', action='store_true'); args = parser.parse_args()
    DOC.mkdir(parents=True, exist_ok=True); OUT.mkdir(parents=True, exist_ok=True)
    lock = open(OUT/'runner.lock', 'a'); fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    closure = json.loads((DOC.parent/'deep_intraday_sequence_v2/FORMAL_CLOSURE.json').read_text())
    assert closure['closed'] and not closure['remaining_required_minute_work']
    spec = json.loads((DOC/'SPEC.json').read_text()); config = spec['config']; spec_hash = sha(DOC/'SPEC.json')
    assert spec['source_sha256'] == sha(Path(__file__))
    data = Data(); preflight(data, config)
    if not args.run: return
    birth = subprocess.check_output(['ps','-p',str(os.getpid()),'-o','lstart='], text=True).strip()
    try:
        for seed in SEEDS:
            for arm in ARMS:
                write(DOC/'AUTONOMOUS_STATE.json', dict(at=stamp(), CURRENT_PHASE='MATCHED_TRAINING',
                      active_run=f'{arm}_s{seed}', pid=os.getpid(), birth=birth,
                      NEXT_AUTHORIZED_ACTION='Finish same-seed A/B/C then next fixed seed; summarize common-support Train metrics; annual accounts require integration parity; no post2019 payloads'))
                train(data, config, arm, seed, spec_hash)
            complete = [json.loads((OUT/f'{a}_s{seed}/COMPLETE.json').read_text()) for a in ARMS]
            assert len({c['draw_counts_sha256'] for c in complete}) == 1
            assert len({json.dumps(c['sampler_state'],sort_keys=True) for c in complete}) == 1
        write(DOC/'AUTONOMOUS_STATE.json', dict(at=stamp(), CURRENT_PHASE='MATCHED_TRAINING_AND_BASIC_EVAL_COMPLETE',
              pid=None, NEXT_AUTHORIZED_ACTION='Agent builds fixed3 common-support decomposition and yearly RMB1m account integration parity; no new model choice'))
    except Exception as e:
        write(DOC/'AUTONOMOUS_STATE.json', dict(at=stamp(), CURRENT_PHASE='NEEDS_AGENT_REPAIR', pid=None,
              error=repr(e), resume='same --run command; completed runs reused and LAST optimizer/RNG restored'))
        raise


if __name__ == '__main__':
    torch.set_num_threads(2)
    main()
