"""Accept only specifically certified cache identities; preserve generator receipts."""
import json
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.data import OUT


def verify_cache(receipt, identity):
    saved=json.loads(receipt.read_text())
    if saved['identity']!=identity:
        certificate=json.loads((OUT/'engine_equivalence_certificate.json').read_text())
        entry=certificate['accounts'].get(str(receipt.parent.relative_to(OUT)))
        if not entry or entry['receipt_sha256']!=repair.digest(receipt) or entry['accepted_identity']!=identity:
            raise ValueError('cached configuration binding changed without exact equivalence certificate')
        for name,digest in certificate['evidence_hashes'].items():
            if repair.digest(OUT/name)!=digest:raise ValueError('equivalence evidence drift')
    for name,digest in saved['hashes'].items():
        if repair.digest(receipt.parent/name)!=digest:raise ValueError('cached account artifact drift')
    return saved
