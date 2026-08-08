"""cfc — the 2.0 parallel boundary.

Not the application. This package's only useful command right now is
`python -m cfc doctor`, which reads the trusted repository-root `config.py`
once, validates the bootstrap settings 2.0 needs, and reports readiness
without changing anything on disk. The v1.9.1 flat application (`main.py`,
via `launch.sh`) remains the daily-use route — see `HANDOVER.md`.
"""
