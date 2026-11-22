# FR-23 containment fixture — attempts network egress. Run ONLY inside the hardened sandbox
# (`lattice render-sandbox tests/fixtures/net_egress.py`). With `--network=none` there is no
# route off the container, so the connection fails fast. Expected outcome: non-zero exit.
import socket
import sys

try:
    with socket.create_connection(("1.1.1.1", 53), timeout=5):
        print("EGRESS SUCCEEDED — sandbox is NOT contained")
        sys.exit(0)  # if this ever happens, the sandbox failed
except OSError as e:
    print(f"egress blocked (contained): {e}")
    sys.exit(1)  # the expected, contained outcome
