"""verification/ — the reliability layer (M2 / Phase 1). The moat.

Two-layered, never conflated: the free `compile_repair` check gates every paid
`vision_critic` call; `best_of_n` is the non-convergence fallback; `caps` guarantees no loop
ever hangs. See README.md.
"""
