# Classical Delphi Method Demonstration

## Overview

This document serves as the demonstration companion and technical reference for the executable **Classical Delphi** orchestration implemented in Decidero GDSS. It accompanies the research paper on executable collaboration engineering submitted to the Hawaii International Conference on System Sciences (HICSS).

The core thesis demonstrated herein is that multi-stage collaborative methods can be expressed purely as **declarative orchestration documents (Layer 2)** executed over **generic, frozen activity plugins (Layer 1)** and **shared runtime primitives (Layer 3)**, obviating bespoke activity implementations.

---

## Method Specification

* **Method:** Classical Delphi (Iterative Consensus with Controlled Feedback)
* **Citation:** Linstone, H. A., & Turoff, M. (Eds.). (1975). *The Delphi Method: Techniques and Applications*. Addison-Wesley.
* **Orchestration Source:** [`orchestrations/delphi.json`](../orchestrations/delphi.json)
* **Canary Identifier:** `Oracular Quokka`

### Process Workflow

```
[ Generate Items ] ──> [ Round 1: Rank Order ] ──> [ Compute Aggregation & IQR ]
                             │                                 │
                             ▼                                 ▼
                     [ Convergence Met? ] ──Yes──> [ Final Report ]
                             │ No
                             ▼
                 [ Outlier Justification / Comments ]
                             │
                             ▼
                 [ Next Round: Re-Rank ]
```

1. **Generation (Round 1):** Participants generate initial candidate items anonymously via the standard `brainstorming` activity.
2. **Evaluation & Ranking:** Items enter an iterative loop (`iterate` construct with `max_rounds: 4`). Participants rank items using `rank_order_voting`.
3. **Statistical Aggregation & Transform:**
   - The engine executes the `delphi_statistical_aggregation` transform.
   - For each item, median rank, interquartile range (IQR), and mean absolute deviation from median (MAD-M / dispersion) are calculated.
   - Outliers are identified based on distance from the group median.
4. **Convergence Assessment:**
   - Evaluated by the `iqr_stability` predicate against a defined threshold ($\Delta \text{IQR} \le 0.15$).
   - If consensus stability is reached or `max_rounds` is exhausted, the loop terminates.
5. **Controlled Feedback & Deliberation:**
   - Statistical feedback (medians, IQRs, outlier tags) is displayed back to participants.
   - Participants whose prior rankings diverged provide rationale via a comment/justification step. Rather than using a bespoke tool, this step leverages the standard `brainstorming` plugin configured as a commentary surface.

---

## Technical Architecture (Layered Model)

1. **Layer 1 — Reusable Activities:**
   - `brainstorming` (`app/plugins/builtin/brainstorming/`)
   - `rank_order_voting` (`app/plugins/builtin/rank_order_voting/`)
2. **Layer 2 — Orchestration Document:**
   - `orchestrations/delphi.json` (Validated against `docs/schemas/orchestration.schema.json`)
3. **Layer 3 — Runtime Primitives & Engine:**
   - Orchestration engine: `app/services/agenda_strategy.py`
   - Predicate registry: `app/services/orchestration_predicates.py` (`iqr_stability`)
   - Transform registry: `app/services/orchestration_transforms.py` (`delphi_statistical_aggregation`)
   - Session & Report Generation: `app/services/report_service.py`
4. **Layer 4 — Data Bundles:**
   - Transfer between activities conforms to `docs/schemas/bundle_payload.schema.json`.

---

## Replication & Test Execution

The deterministic execution and convergence behavior of the Delphi orchestration are validated via synthetic cohorts:

```bash
PYTHONPATH=. ./venv/bin/pytest app/tests/test_orchestration_engine.py -k delphi -v
```

See [`docs/DELPHI_VALIDATION.md`](DELPHI_VALIDATION.md) for full fixture data, IQR regime validation, and analytical proofs.

---

## Demonstration Materials (Conference Artifacts)

<!-- Section reserved for conference demonstration links, figures, and session exports -->

### Session Setup
* Instructions for initializing a live meeting using `orchestrations/delphi.json`.

### Screenshots & Walkthrough
* *Interface views: Brainstorming -> Ranking -> Statistical Feedback -> Convergence Gate.*

### Data Export & Sample Payloads
* Sample payload: `docs/schemas/examples/report_payload.delphi-bls.example.json`
