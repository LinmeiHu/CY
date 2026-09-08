"""Record actual tests, rerun the rejection, and hash reviewable artifacts."""
import json
import xml.etree.ElementTree as ET

import pandas as pd

from . import audit, build_report


def outputs():
    return {str(p.relative_to(audit.HERE)): audit.sha256(p)
            for p in sorted(audit.HERE.rglob('*')) if p.is_file()
            and '__pycache__' not in p.parts
            and p.suffix not in ('.log', '.xml', '.pyc')
            and p.name not in ('determinism.csv', 'output_manifest.sha256')}


def main():
    cases = []
    for case in ET.parse(audit.OUT / 'tests.xml').getroot().iter('testcase'):
        status = 'SKIPPED' if case.find('skipped') is not None else 'PASS'
        if case.find('failure') is not None or case.find('error') is not None:
            status = 'FAIL'
        cases.append(dict(name=case.attrib['classname'] + '::' + case.attrib['name'], status=status))
    if not cases or any(c['status'] == 'FAIL' for c in cases):
        raise ValueError('actual test suite failed or absent')
    audit.write_json(audit.OUT / 'test_results.json', dict(
        command='/opt/anaconda3/bin/python -m pytest -q tests research --junitxml=research/scaling_regime_v1/output/tests.xml',
        passed=sum(c['status']=='PASS' for c in cases), skipped=sum(c['status']=='SKIPPED' for c in cases),
        tests=sorted(cases,key=lambda r:r['name']),
        interpretation='Tests pass for identity rejection; downstream economic tests not run'))
    assert audit.run() == 2
    build_report.main()
    before = outputs()
    assert audit.run() == 2
    build_report.main()
    after = outputs()
    if before != after:
        raise ValueError('nondeterministic identity outputs')
    pd.DataFrame([dict(path=k, before_sha256=v, after_sha256=after[k], status='PASS')
                  for k,v in before.items()]).to_csv(audit.OUT / 'determinism.csv', index=False)
    final = outputs()
    final['output/determinism.csv'] = audit.sha256(audit.OUT / 'determinism.csv')
    (audit.OUT / 'output_manifest.sha256').write_text(''.join(f'{v}  {k}\n' for k,v in sorted(final.items())))
    print(json.dumps(dict(test_cases=len(cases), deterministic_files=len(before), manifest_files=len(final),
                          task_status='BLOCKED_ROLLFORWARD_IDENTITY_MISMATCH')))


if __name__ == '__main__':
    main()
