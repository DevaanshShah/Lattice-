"""M5 unit tests — bounded parallel pool (T-15). No network."""
import threading

import pytest


@pytest.mark.unit
def test_runs_all_in_order():
    from composition.pool import run_bounded
    res = run_bounded(["a", "b", "c"], lambda item, i: f"{i}:{item}", cap=2)
    assert [r.value for r in res] == ["0:a", "1:b", "2:c"]
    assert all(r.ok for r in res)


@pytest.mark.unit
def test_failure_is_isolated():
    from composition.pool import run_bounded

    def work(item, i):
        if i == 1:
            raise RuntimeError("scene 1 blew up")
        return item.upper()

    res = run_bounded(["a", "b", "c"], work, cap=3)
    assert res[0].ok and res[0].value == "A"
    assert res[1].ok is False and "blew up" in res[1].error
    assert res[2].ok and res[2].value == "C"     # others still completed


@pytest.mark.unit
def test_respects_concurrency_cap():
    from composition.pool import run_bounded

    lock = threading.Lock()
    state = {"now": 0, "max": 0}
    gate = threading.Event()

    def work(item, i):
        with lock:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        gate.wait(0.05)       # hold the slot briefly so overlap is observable
        with lock:
            state["now"] -= 1
        return i

    run_bounded(list(range(6)), work, cap=2)
    gate.set()
    assert state["max"] <= 2          # never more than `cap` running at once


@pytest.mark.unit
def test_empty_items():
    from composition.pool import run_bounded
    assert run_bounded([], lambda item, i: item) == []
