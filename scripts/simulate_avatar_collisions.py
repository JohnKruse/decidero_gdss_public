#!/usr/bin/env python3
"""Simulate deterministic avatar collisions for representative cohort sizes."""

from __future__ import annotations

import argparse
from collections import Counter

from app.services.avatar_catalog import pick_avatar_key, list_avatar_entries


def run_simulation(size: int, seed: int = 0) -> dict:
    avatar_keys = []
    for i in range(1, size + 1):
        user_id = f"SIMUSER-{i:04d}"
        key = pick_avatar_key(user_id=user_id, avatar_seed=seed)
        avatar_keys.append(key or "none")

    counts = Counter(avatar_keys)
    unique = len(counts)
    duplicate_users = sum(count - 1 for count in counts.values() if count > 1)
    duplicated_keys = sum(1 for count in counts.values() if count > 1)
    max_bucket = max(counts.values()) if counts else 0
    return {
        "size": size,
        "unique_keys": unique,
        "duplicate_users": duplicate_users,
        "duplicated_keys": duplicated_keys,
        "max_users_on_single_key": max_bucket,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sizes",
        nargs="+",
        type=int,
        default=[50, 100, 200],
        help="Cohort sizes to evaluate.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Avatar seed used for all simulated users.",
    )
    args = parser.parse_args()

    catalog_size = len(list_avatar_entries())
    print(f"catalog_size={catalog_size}")
    for size in args.sizes:
        result = run_simulation(size=size, seed=args.seed)
        print(
            "size={size} unique_keys={unique_keys} duplicate_users={duplicate_users} "
            "duplicated_keys={duplicated_keys} max_users_on_single_key={max_users_on_single_key}".format(
                **result
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
