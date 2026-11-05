# Simplest sweep: server change factor x FIB update threshold on the DFN
# example, 360 s per run, one main.py call each, logs in logs/.
# Run from the repository root:  python3 experiments/sweep_simple.py

import subprocess

for cf in [0.001, 0.01, 0.05]:
    for fib in [0.0001, 0.001, 0.01]:
        log = f"logs/dfn_cf{cf}_fib{fib}.log"
        print(log)
        with open(log, "w") as out:
            subprocess.run(["python3", "experiments/main.py", "configs/dfn_s5_c5.py",
                            "--set", "UNTIL=360000",
                            "--set", f"SERVER_CF={cf}",
                            "--set", f"ROUTER_FIB_UPT={fib}"], stdout=out)
