# FR-23 containment fixture — a fork bomb. Run ONLY inside the hardened sandbox
# (`lattice render-sandbox tests/fixtures/fork_bomb.py`); NEVER on the host.
# `--pids-limit` caps live processes, so os.fork() starts failing and the run dies
# bounded instead of taking the machine down. Expected outcome: non-zero exit, host untouched.
import os

while True:
    try:
        os.fork()
    except OSError:
        # pids-limit reached: the cap is doing its job. Spin so the wall-clock kill also fires.
        pass
