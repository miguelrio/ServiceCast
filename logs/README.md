# Run logs

A place for the logs of runs of `experiments/main.py`, which writes its log
to stdout:

```bash
python3 experiments/main.py configs/dfn_s5_c5.py > logs/dfn_s5_c5.log
```

Nothing here is committed (see `.gitignore`); keep results that matter
elsewhere. `main.py` never writes files itself, so where a log goes is the
caller's choice.
