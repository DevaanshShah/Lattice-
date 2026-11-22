# tests/

The pytest harness. Each milestone ends by extending these (see the Test & Ship Gate in `MILESTONES.md`).

**Conventions**
- Markers: `unit` (hard gate, must be green to commit — no network), `integration` (needs a render container; gated behind an env flag), `llm` (calls a model; **deferred** by default, run only with an explicit flag).
- `conftest.py` holds fixtures: a fake LLM client, a sample scene spec, a tiny render stub.
- Unit tests never call a real model or render a real video — they assert schema validation, cap behaviour, cache-key determinism, and graceful failure.

**Maps to:** every milestone (M0 lands the harness itself).
