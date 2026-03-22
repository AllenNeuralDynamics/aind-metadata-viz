"""Modality-based completeness evaluation for AIND sessions.

``check_completeness`` takes a ``SessionResult`` and returns a
``CompletenessResult`` describing whether all expected derived processing
has been done.

When the DTS job type is known (``session.expected_pipelines`` is not None),
those modalities are used as the expected set — this gives per-session
precision (e.g. a behavior-only session is complete with just a behavior
derived asset, even if the project also supports fiber).

When there is no DTS job (``expected_pipelines`` is None), the function falls
back to ``session.raw_modalities`` minus the project-level
``no_derived_expected`` exclusion set (modalities that are collected but
intentionally never processed into derived assets, e.g. behavior-videos).
"""

from __future__ import annotations

from dataclasses import dataclass

from aind_session_utils.session import SessionResult


@dataclass(frozen=True)
class CompletenessResult:
    """Completeness evaluation result for one session."""

    status: str                         # 'complete'|'partial'|'no_derived'|'no_raw_asset'
    expected_modalities: frozenset[str]
    covered_modalities: frozenset[str]
    missing_modalities: frozenset[str]
    excluded_modalities: frozenset[str]


def check_completeness(
    session: SessionResult,
    no_derived_expected: frozenset[str] = frozenset(),
) -> CompletenessResult:
    """Check whether a session's derived processing is complete.

    Args:
        session: The session to evaluate.
        no_derived_expected: Modalities that are collected but intentionally
            not processed into derived assets (e.g. ``behavior-videos``).
            Only used as a fallback when ``expected_pipelines`` is None.

    Returns:
        ``CompletenessResult`` with status and modality set breakdown.
    """
    _empty: frozenset[str] = frozenset()

    if session.raw_asset_name is None:
        return CompletenessResult(
            status="no_raw_asset",
            expected_modalities=_empty,
            covered_modalities=_empty,
            missing_modalities=_empty,
            excluded_modalities=_empty,
        )

    # Determine which modalities are expected to have derived coverage.
    if session.expected_pipelines is not None:
        # DTS job type gives per-session precision.
        expected = session.expected_pipelines
        excluded = _empty
    else:
        # No DTS job — fall back to raw modalities minus project exclusions.
        excluded = session.raw_modalities & no_derived_expected
        expected = session.raw_modalities - no_derived_expected

    covered = frozenset(m for da in session.derived_assets for m in da.modalities)
    covered_of_expected = covered & expected
    missing = expected - covered_of_expected

    if not expected:
        status = "complete"
    elif not session.derived_assets:
        status = "no_derived"
    elif missing:
        status = "partial"
    else:
        status = "complete"

    return CompletenessResult(
        status=status,
        expected_modalities=expected,
        covered_modalities=covered_of_expected,
        missing_modalities=missing,
        excluded_modalities=excluded,
    )
