"""Version the attribution boundary assumption without changing state families."""
import json
from datetime import datetime,timezone
from .audit import HERE,sha256,write_json


def main():
    original=HERE/'contracts/scaling_regime_attribution_v1.json'
    contract=json.loads(original.read_text())
    contract.update(version='CAPITAL_SCALING_REGIME_ATTRIBUTION_V2_CONTINUOUS',supersedes_sha256=sha256(original),
        continuous_protocol_sha256=sha256(HERE/'contracts/continuous_rollforward_protocol_v1.json'),
        parent_boundary_semantics='AUTHORITATIVE_CONTINUOUS_PROTOCOL_V1; initialize once from frozen 2018 state and carry all state. Segmented parent is a separately labeled comparator',
        identity_gate='Continuous source, restored predicates, historical prefix and temporal prefix gates all PASS before outcome attribution',
        amendment_reason='V1 explicitly required per-segment SMV6 reset. User now authorizes source-defined continuous initialization; preserve all existing state features, thresholds, targets and qualification requirements',
        state_outcome_allocation='Each daily scaled-minus-native actual P&L counted once, conditioned on previous completed daily state; decision table separately counts actual normalization times. Overlapping horizon diagnostics are not summed as independent annual P&L',
        attribution_limits='Annual amount difference contains accumulated capital/path differences; mechanics comparison is a controlled account experiment, not multiplication of historical trade returns',
        router_assessment='First one-dimensional market regime and existing breadth only; evaluate leave-one-year-out direction and remove top 5 profitable root contributions without refitting. No new high-low bins for volatility/DD/liquidity or 2D search',
        router_independent_date_disclosure='Report dates, decisions, annual blocks and root concentration rather than inventing a sample-size cutoff. Require positive direction in every discovery/confirmation leave-year block and after top-5 event removal to support the claimed stable positive scaling state',
        cash_residual='Observed uninvested cash has zero assumed interest; no invented foregone return',
        full_book_forward='Signed marginal fill quantity times forward total-return price change, with actual closing executions/CA adjustments where available; label counterfactual reductions and overlap, never treat full horizon sum as actual annual P&L')
    path=HERE/'contracts/scaling_regime_attribution_v2.json'
    if path.exists():assert json.loads(path.read_text())==contract
    else:
        write_json(path,contract)
        write_json(HERE/'contracts/attribution_v2_freeze_receipt.json',dict(sha256=sha256(path),frozen_at=datetime.now(timezone.utc).isoformat(),state_conditioned_outcomes_started=False,old_v1_unchanged=True))
    print('ATTRIBUTION_V2_FROZEN',sha256(path),flush=True)


if __name__=='__main__':main()
