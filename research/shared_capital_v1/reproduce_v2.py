"""Fail-closed full continuous reconstruction, P0 and frozen 48-cell study."""
import subprocess
import sys
from .continuous_replay import run as stocks
from .validate_continuous import run as prefixes
from .common_p0_v06 import run as p0
from .shared_study import run as study
from .final_analysis import run as analysis


def main():
    stocks()
    prefixes()
    subprocess.run([sys.executable,'-m','pytest','-q','research/shared_capital_v1/tests','tests/unit','--junitxml=research/shared_capital_v1/cache/v2_tests.xml'],check=True)
    p0()
    study()
    from .validate_rerun_v2 import run as deterministic_reruns
    deterministic_reruns()
    analysis()
    from .finalize_v2 import run
    run()

if __name__=='__main__':main()
