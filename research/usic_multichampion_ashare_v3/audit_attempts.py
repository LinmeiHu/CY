"""Keep physical replay attempts separate from the registered experiment count."""
import collections
import json
from .common import HERE, OUT, sha, dump


def main():
    rows = []
    for p in sorted(OUT.glob('*.log')):
        counts = collections.Counter()
        ids = []
        for line in p.read_text(errors='replace').splitlines():
            fields = line.split()
            if len(fields) >= 3 and fields[0] in ['ACCOUNT', 'Q_ACCOUNT']:
                counts[fields[2]] += 1
                ids.append(fields[1])
            elif len(fields) >= 2 and fields[0] == 'RESUME_VERIFIED':
                counts['CHECKPOINT_HASH_VERIFIED_NO_NEW_REPLAY'] += 1
        if counts:
            rows.append(dict(log=str(p), sha256=sha(p), records=dict(counts), ids=ids, repeat_validation=p.name.startswith('repeat_')))
    comparisons = []
    for name in ['core_before_official_backfill', 'before_final_action_backfill']:
        states = collections.Counter()
        valid = []
        for p in sorted((OUT/name).glob('*/result.json')):
            old = json.loads(p.read_text())
            states[old['status']] += 1
            if old['status'] != 'COMPLETED_NEW':
                continue
            old_identity = json.loads((p.parent/'identity.json').read_text())
            final_identity = json.loads((OUT/p.parent.name/'identity.json').read_text())
            checks = {n: sha(p.parent/n) == final_identity['artifacts'][n] for n in old_identity['artifacts']}
            valid.append(dict(id=p.parent.name, all_six_artifacts_unchanged=all(checks.values()), checks=checks))
        comparisons.append(dict(snapshot=str(OUT/name), states=dict(states), completed_accounts_compared=len(valid), all_completed_unchanged=all(x['all_six_artifacts_unchanged'] for x in valid), completed_accounts=valid))
    totals = collections.Counter()
    for row in rows:
        totals.update(row['records'])
    dump(HERE/'RUN_ATTEMPTS.json', dict(unique_registered_slots=296, final_complete_new_accounts=252, physical_log_records=dict(totals), logs=rows, historical_snapshots=comparisons, interpretation='Operational reruns after official execution facts and deterministic repeats are not new hypotheses. Checkpoint verification is not a new account run or reuse of a prior research account.', interruption='One final core driver exited by SIGTERM (143); completed atomic cases survived, then --groups C,D,E,Q resumed to completion.', bug_result_impact='Feature/eligibility/expiry and Q5 mapping fixes preceded their first account outcomes; no completed pre-bug account is a valid economic comparator. Unfinished action-blocked accounts have no full-period return to subtract. Historical complete artifact equality is measured above.'))
    print('ATTEMPT_RECORDS', dict(totals))
    print('HISTORICAL_COMPLETE_PARITY', [(x['completed_accounts_compared'], x['all_completed_unchanged']) for x in comparisons])


if __name__ == '__main__':
    main()
