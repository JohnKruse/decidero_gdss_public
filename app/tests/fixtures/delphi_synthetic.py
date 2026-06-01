"""Oracular Quokka: deterministic synthetic Delphi cohort fixture.

The ranking regimes exercise high dispersion, contraction that does not yet
fire `IQRStabilityPredicate`, terminal stability, and a non-stabilizing path
used to verify the orchestration engine's `max_rounds` ceiling.
"""

IDEAS = [
    "Reduce handoff latency",
    "Improve meeting preparation",
    "Standardize decision records",
    "Automate follow-up tracking",
    "Expose confidence intervals",
]

PARTICIPANTS = [
    ("u-delphi-p1", "delphip1"),
    ("u-delphi-p2", "delphip2"),
    ("u-delphi-p3", "delphip3"),
    ("u-delphi-p4", "delphip4"),
    ("u-delphi-p5", "delphip5"),
]

HIGH_IQR_OPENING_ROUND = [
    [IDEAS[0], IDEAS[1], IDEAS[2], IDEAS[3], IDEAS[4]],
    [IDEAS[0], IDEAS[4], IDEAS[2], IDEAS[3], IDEAS[1]],
    [IDEAS[0], IDEAS[2], IDEAS[3], IDEAS[4], IDEAS[1]],
    [IDEAS[0], IDEAS[3], IDEAS[1], IDEAS[4], IDEAS[2]],
    [IDEAS[4], IDEAS[3], IDEAS[2], IDEAS[1], IDEAS[0]],
]

CONTRACTED_INTERMEDIATE_ROUND = [
    [IDEAS[0], IDEAS[1], IDEAS[2], IDEAS[3], IDEAS[4]],
    [IDEAS[0], IDEAS[1], IDEAS[2], IDEAS[3], IDEAS[4]],
    [IDEAS[1], IDEAS[0], IDEAS[2], IDEAS[3], IDEAS[4]],
    [IDEAS[0], IDEAS[2], IDEAS[1], IDEAS[3], IDEAS[4]],
    [IDEAS[0], IDEAS[1], IDEAS[3], IDEAS[2], IDEAS[4]],
]

TERMINAL_STABLE_ROUND = CONTRACTED_INTERMEDIATE_ROUND

NON_STABILIZING_ROUNDS = [
    HIGH_IQR_OPENING_ROUND,
    CONTRACTED_INTERMEDIATE_ROUND,
    HIGH_IQR_OPENING_ROUND,
    CONTRACTED_INTERMEDIATE_ROUND,
]
