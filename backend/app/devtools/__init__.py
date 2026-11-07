"""Operations/test tooling package: shared safety helpers for object cleanup and test tools.

Imported lazily by CLIs only and never loaded at service startup; ``.env.prod`` is not read.
The test identity seed lives in ``tests.acceptance_real.seed``; application modules do not
depend on tests in reverse.
"""

__all__: list[str] = []
