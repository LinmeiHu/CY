# Reproduction

From repository root:

```bash
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run --stage signals
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run_native --scenario BASE
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run_native --scenario COST2
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run_native --scenario DELAY1
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run_native --scenario BASE --repeat
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run_legacy
PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.analyze
PYTHONPATH=. python -m unittest research.ashare_champion_playbooks_v1.test_native research.ashare_champion_playbooks_v1.test_playbooks
```

Large authoritative artifacts are under `/Volumes/quant/CY_quant_research/ashare_champion_playbooks_v1`; compact tables and contracts are in Git.
