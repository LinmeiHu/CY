import json

import pandas as pd
import pytest

from research.capital_scaling_v1 import finalize, run


def test_habitat_cannot_start_from_partial_grid_even_with_existing_gate(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import habitat
    (tmp_path/'output').mkdir()
    (tmp_path/'output/research_gate.json').write_text('{"status":"NOT_RUN"}')
    monkeypatch.setattr(habitat, 'HERE', tmp_path)
    monkeypatch.setattr(habitat, 'load_bounded', lambda *_: pytest.fail('habitat data loaded before complete grid'))
    with pytest.raises(ValueError, match='full scaling grid'):
        habitat.run(pd.DataFrame())


@pytest.mark.parametrize('corruption', ['missing_hashes', 'wrong_case'])
def test_finalization_rejects_unverified_scenario_receipt(tmp_path, monkeypatch, corruption):
    case = run.scenarios()[0][0]
    folder = tmp_path/'case'
    folder.mkdir()
    hashes = {}
    for name in run.ACCOUNT_ARTIFACTS:
        path = folder/name
        path.write_text('artifact')
        hashes[name] = run.sha256(path)
    evidence = dict(case=case, hashes=hashes, validation='PASS')
    if corruption == 'missing_hashes':
        evidence['hashes'] = {}
    else:
        evidence['case'] = dict(case, strategy='MCB')
    (folder/'receipt.json').write_text(json.dumps(evidence))
    monkeypatch.setattr(finalize, 'OUT', tmp_path)
    with pytest.raises(ValueError, match='receipt|identity'):
        finalize.external_manifest(pd.DataFrame([dict(case, source=str(folder))]))
    assert not (tmp_path/'external_artifact_manifest.csv').exists()


@pytest.mark.parametrize('corruption', ['duplicated_rows', 'changed_fresh_file'])
def test_deterministic_proof_requires_distinct_actual_matching_files(tmp_path, monkeypatch, corruption):
    monkeypatch.setattr(finalize, 'EXTERNAL', tmp_path)
    cases = run.scenarios()[1][:6]
    table, evidence = [], []
    for case in cases:
        key = run.case_key(case)
        source = tmp_path/'runs'/key
        actual = tmp_path/'deterministic'/'fresh'/key
        source.mkdir(parents=True)
        actual.mkdir(parents=True)
        table.append(dict(case, source=str(source)))
        for name in (*run.ACCOUNT_ARTIFACTS, 'scaling.json'):
            (source/name).write_text(key+name)
            (actual/name).write_text(key+name)
            digest = run.sha256(source/name)
            evidence.append(dict(case=key, artifact=name, actual_path=str(actual/name),
                                 expected_sha256=digest, actual_sha256=digest, engine_identity='identity', status='PASS'))
    frame = pd.DataFrame(evidence)
    finalize.verify_deterministic(frame, pd.DataFrame(table), 'identity')
    if corruption == 'duplicated_rows':
        frame.iloc[-1] = frame.iloc[0]
    else:
        from pathlib import Path
        Path(frame.actual_path.iloc[0]).write_text('changed')
    with pytest.raises(ValueError, match='fresh|actual'):
        finalize.verify_deterministic(frame, pd.DataFrame(table), 'identity')
