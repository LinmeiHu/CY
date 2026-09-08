cd /Users/linmei/Documents/CY-worktrees/five-strategy-native-decomposition-v1
export PYTHONPATH=.:src
/opt/anaconda3/bin/python research/native_decomposition_v1/run.py
/opt/anaconda3/bin/python -m pytest -q research/native_decomposition_v1/test_decomposition.py
