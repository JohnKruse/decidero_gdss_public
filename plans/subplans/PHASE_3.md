# Phase 3 — Frontend UI [COMPLETE]

**Parent:** `plans/01_MASTER_PLAN.md`
**Depends on:** `plans/subplans/PHASE_2.md` (Phase 2 complete — backend commit branch fully functional)
**Global Canary:** `Turquoise Wombat`
**Phase Canary:** `Galactic Hamster`

---

## Overview

Add a target-mode selector to the transfer panel so facilitators can choose between "Create new activity" (existing behavior) and "Transfer to existing activity" (new). When the existing-activity mode is selected, a dropdown of agenda activities appears with ineligible activities grayed out and disabled. The commit button text, payload construction, and post-commit behavior all adapt to the selected mode.

All backend work is done (Phase 2). This phase is purely frontend: HTML, JS, and CSS.

---

## Step 1: [DONE] Extend `transferState` and the DOM Reference Object

**File:** `app/static/js/meeting.js` (lines 831-847 for `transferState`, lines 397-411 for `transfer` DOM refs)

**Implement:**
Add two new fields to `transferState` (after line 846):
```javascript
targetMode: "new",         // "new" | "existing"
targetActivityId: null,    // activity_id when mode is "existing"
```

In `resetTransferState()` (~line 3497-3531), add resets:
```javascript
transferState.targetMode = "new";
transferState.targetActivityId = null;
```

Add two new DOM references to the `transfer` object (after line 410):
```javascript
targetMode: document.getElementById("transferTargetMode"),
targetExistingActivity: document.getElementById("transferTargetExistingActivity"),
transferEligibilityHint: document.getElementById("transferEligibilityHint"),
```

**Test:** Add to `app/tests/test_frontend_smoke.py`:
- `test_transfer_panel_has_target_mode_elements` — Read `meeting.js` as text. Assert it contains `"transferTargetMode"`, `"transferTargetExistingActivity"`, `targetMode: "new"`, and `targetActivityId: null`.

**Docs:** Add inline JS comment above the new state fields: `// Target mode: "new" creates an activity, "existing" transfers into a pre-existing one`.

**Technical Deviations Logged:**
- The step text says "Add two new DOM references" but lists three (`targetMode`, `targetExistingActivity`, `transferEligibilityHint`). Implemented all three listed references to align with downstream Steps 2-4.
- `pytest` was not available on PATH in this shell, so verification ran via `venv/bin/pytest app/tests/test_frontend_smoke.py -v`.

---

## Step 2: [DONE] Add HTML Elements to the Transfer Panel

**File:** `app/templates/meeting.html` (lines 158-203, the transfer panel section)

**Implement:**
Insert new elements in the `.transfer-actions` div (after the `transferTargetToolType` select, before the `transferTransformProfile` select, approximately line 168):

```html
<select id="transferTargetMode" class="form-select transfer-target-select">
    <option value="new" selected>Create new activity</option>
    <option value="existing">Use existing activity</option>
</select>
<select id="transferTargetExistingActivity"
        class="form-select transfer-target-select"
        hidden>
    <option value="" disabled selected>Select target activity</option>
</select>
<span id="transferEligibilityHint"
      class="transfer-eligibility-hint"
      hidden>
    Only unused activities are eligible to receive transferred ideas.
</span>
```

The `transferTargetMode` select is always visible. The `transferTargetExistingActivity` select and `transferEligibilityHint` are `hidden` by default and revealed by JS when mode is "existing".

**Test:** Add to `app/tests/test_frontend_smoke.py`:
- `test_transfer_panel_html_has_mode_selector` — Read `meeting.html` as text. Assert it contains `id="transferTargetMode"`, `id="transferTargetExistingActivity"`, `id="transferEligibilityHint"`, `value="new"`, and `value="existing"`.

**Docs:** Add HTML comment above the new elements: `<!-- Galactic Hamster: target mode selector for transfer-into-existing -->`.

**Technical Deviations Logged:**
- `pytest` was not available on PATH in this shell, so verification ran via `venv/bin/pytest app/tests/test_frontend_smoke.py -v`.

---

## Step 3: [DONE] Add CSS for Eligibility Hint and Disabled Options

**File:** `app/static/css/meeting.css` (after the `.transfer-target-select:focus` block, ~line 2009)

**Implement:**
Add styles for the eligibility hint and for disabled options in the existing-activity dropdown:

```css
.transfer-eligibility-hint {
    font-size: 0.85rem;
    color: #8896a7;
    font-style: italic;
    white-space: nowrap;
}

.transfer-target-select option:disabled {
    color: #b0b8c4;
    font-style: italic;
}
```

The disabled option styling gives a clear visual gray-out signal. The hint text is subtle but always visible when in "existing" mode.

**Test:** Add to `app/tests/test_frontend_smoke.py`:
- `test_transfer_css_has_eligibility_hint_style` — Read `meeting.css` as text. Assert it contains `transfer-eligibility-hint`.

**Docs:** Add CSS comment: `/* Galactic Hamster: eligibility hint for transfer-into-existing mode */`.

**Technical Deviations Logged:**
- `pytest` was not available on PATH in this shell, so verification ran via `venv/bin/pytest app/tests/test_frontend_smoke.py -v`.

---

## Step 4: [DONE] Implement Mode Toggle Logic

**File:** `app/static/js/meeting.js`

**Implement:**
Add a new function `onTransferModeChange()` and wire it to the mode selector. Place it after `buildTransferTargetOptions()` (~line 3229):

```javascript
function onTransferModeChange() {
    const mode = transfer.targetMode?.value || "new";
    transferState.targetMode = mode;
    transferState.targetActivityId = null;

    const isExisting = mode === "existing";

    // Show/hide the tool-type dropdown (for "new" mode)
    if (transfer.targetToolType) {
        transfer.targetToolType.hidden = isExisting;
    }
    // Show/hide the existing-activity dropdown (for "existing" mode)
    if (transfer.targetExistingActivity) {
        transfer.targetExistingActivity.hidden = !isExisting;
        if (isExisting) {
            buildTransferExistingActivityOptions();
        }
    }
    // Show/hide the transform profile (only for "new" mode with categorization donors)
    if (transfer.transformProfile && isExisting) {
        transfer.transformProfile.hidden = true;
    }
    // Show/hide eligibility hint
    if (transfer.transferEligibilityHint) {
        transfer.transferEligibilityHint.hidden = !isExisting;
    }
    // Update commit button text
    updateTransferCommitButtonText();
}
```

Wire it up in the event listener setup section (near where `transfer.includeComments` and `transfer.targetToolType` listeners are attached):
```javascript
if (transfer.targetMode) {
    transfer.targetMode.addEventListener("change", onTransferModeChange);
}
```

Also add a listener on `transfer.targetExistingActivity` to capture selection:
```javascript
if (transfer.targetExistingActivity) {
    transfer.targetExistingActivity.addEventListener("change", () => {
        transferState.targetActivityId = transfer.targetExistingActivity.value || null;
        updateTransferCommitButtonText();
    });
}
```

**Test:** Add to `app/tests/test_frontend_smoke.py`:
- `test_transfer_js_has_mode_change_handler` — Read `meeting.js` as text. Assert it contains `onTransferModeChange`, `buildTransferExistingActivityOptions`, and `updateTransferCommitButtonText`.

**Docs:** Add inline JS comment: `// Galactic Hamster: toggle between "new" and "existing" transfer target modes`.

**Technical Deviations Logged:**
- Added lightweight implementations for `buildTransferExistingActivityOptions()` and `updateTransferCommitButtonText()` in this step so `onTransferModeChange()` can execute safely; Step 5 will extend these with full eligibility labeling and final button semantics.
- `pytest` was not available on PATH in this shell, so verification ran via `venv/bin/pytest app/tests/test_frontend_smoke.py -v`.

---

## Step 5: [DONE] Build the Existing-Activity Dropdown and Commit Button Text

**File:** `app/static/js/meeting.js`

**Implement:**
Add two new functions after `onTransferModeChange()`:

**`buildTransferExistingActivityOptions()`** — Populates the `transferTargetExistingActivity` select from `state.agenda`, with eligibility filtering:

```javascript
function buildTransferExistingActivityOptions() {
    if (!transfer.targetExistingActivity) return;
    transfer.targetExistingActivity.innerHTML = "";

    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "Select target activity";
    placeholder.disabled = true;
    placeholder.selected = true;
    transfer.targetExistingActivity.appendChild(placeholder);

    const agenda = state.agenda || [];
    for (const item of agenda) {
        // Skip the donor activity itself
        if (item.activity_id === transferState.donorActivityId) continue;

        const option = document.createElement("option");
        option.value = item.activity_id;

        const label = item.title || item.activity_id;
        const typeLabel = (item.tool_type || "").replace(/_/g, " ");
        option.textContent = `${label} (${typeLabel})`;

        // Eligibility check using the transfer_target_eligible flag from Phase 1
        const eligible = Boolean(item.transfer_target_eligible);
        if (!eligible) {
            option.disabled = true;
            // Build reason string
            let reason = "Ineligible";
            if (item.started_at) reason = "Already started";
            else if (item.has_data) reason = "Has participant data";
            else if (item.has_votes) reason = "Has votes";
            else if (item.has_submitted_ballots) reason = "Has submitted ballots";
            option.textContent += ` — ${reason}`;
            option.title = reason;
        }
        transfer.targetExistingActivity.appendChild(option);
    }
}
```

**`updateTransferCommitButtonText()`** — Updates the commit button label dynamically:

```javascript
function updateTransferCommitButtonText() {
    if (!transfer.commit) return;
    if (transferState.targetMode === "existing" && transferState.targetActivityId) {
        const item = state.agendaMap?.get(transferState.targetActivityId);
        const title = item?.title || transferState.targetActivityId;
        transfer.commit.textContent = `Transfer to ${title}`;
    } else {
        transfer.commit.textContent = "Create Next Activity";
    }
}
```

Also call `updateTransferCommitButtonText()` from `resetTransferState()` so the button text resets when the panel closes.

**Test:** Add to `app/tests/test_frontend_smoke.py`:
- `test_transfer_js_has_existing_activity_builder` — Read `meeting.js` as text. Assert it contains `buildTransferExistingActivityOptions`, `transfer_target_eligible`, `"Already started"`, `"Has participant data"`, and `updateTransferCommitButtonText`.

**Docs:** Add JSDoc-style comments above both functions describing their purpose and when they're called.

**Technical Deviations Logged:**
- Step 4 had already introduced placeholder versions of `buildTransferExistingActivityOptions()` and `updateTransferCommitButtonText()`; this step refined those same functions in place to add eligibility reason labels and title-aware commit text.
- `pytest` was not available on PATH in this shell, so verification ran via `venv/bin/pytest app/tests/test_frontend_smoke.py -v`.

---

## Step 6: [DONE] Modify `commitTransfer()` for Dual-Mode Payload and Post-Commit

**File:** `app/static/js/meeting.js` (lines 3726-3787, the `commitTransfer` function)

**Implement:**
Replace the existing `commitTransfer()` body to support both modes:

1. **Validation** (~line 3735-3738): Replace the single `targetTool` check with mode-aware validation:
   ```javascript
   const isExistingMode = transferState.targetMode === "existing";
   if (isExistingMode) {
       if (!transferState.targetActivityId) {
           throw new Error("Select an existing activity to transfer into.");
       }
   } else {
       const targetTool = transfer.targetToolType?.value;
       if (!targetTool) {
           throw new Error("Select a next activity type.");
       }
   }
   ```

2. **Status message** (~line 3733): Make it mode-aware:
   ```javascript
   setTransferStatus(
       isExistingMode ? "Transferring ideas..." : "Creating next activity...",
       "info",
   );
   ```

3. **Payload construction** (~lines 3745-3753): Branch on mode:
   ```javascript
   const targetPayload = isExistingMode
       ? { activity_id: transferState.targetActivityId }
       : { tool_type: transfer.targetToolType.value };
   // ... in the body:
   target_activity: targetPayload,
   ```

4. **Post-commit handling** (~lines 3760-3778): Branch on mode:
   ```javascript
   if (Array.isArray(data.agenda)) {
       renderAgenda(data.agenda);
   }
   const targetActivity = data.target_activity || data.new_activity || null;
   const targetId = targetActivity?.activity_id || null;
   if (targetId) {
       selectAgendaItem(targetId, { source: "user" });
       localStorage.setItem(
           `transfer:lastActivity:${context.meetingId}`,
           targetId,
       );
   }
   if (isExistingMode) {
       // Existing target: just close the panel and select the activity.
       // No redirect to settings — the activity is already configured.
       setTransferStatus("Ideas transferred successfully.", "success");
       closeTransferModal();
   } else {
       // New activity: redirect to settings page (existing behavior)
       setTransferStatus("Next activity created.", "success");
       closeTransferModal();
       const settingsUrl = `/meeting/${encodeURIComponent(context.meetingId)}/settings`;
       if (targetId) {
           window.location.href = `${settingsUrl}?activity_id=${encodeURIComponent(targetId)}`;
       } else {
           window.location.href = settingsUrl;
       }
   }
   ```

5. **Error message** (~line 3781): Make it mode-aware:
   ```javascript
   setTransferError(error.message || (isExistingMode
       ? "Unable to transfer ideas."
       : "Unable to create next activity."));
   ```

**Test:** Add to `app/tests/test_frontend_smoke.py`:
- `test_transfer_js_commit_handles_both_modes` — Read `meeting.js` as text. Assert it contains `isExistingMode`, `"Select an existing activity to transfer into."`, `activity_id: transferState.targetActivityId`, `"Ideas transferred successfully."`, and `data.target_activity`.

**Docs:** Add inline JS comment at the top of the dual-mode block: `// Galactic Hamster: dual-mode commit — "new" creates, "existing" transfers into`.

**Technical Deviations Logged:**
- The canary inline comment uses an ASCII hyphen (`-`) in `"new" creates, "existing" transfers into` to keep formatting/style consistent with existing JS comments.
- `pytest` was not available on PATH in this shell, so verification ran via `venv/bin/pytest app/tests/test_frontend_smoke.py -v`.

---

## Step 7: [DONE] Integration Verification, `setTransferButtonsState` Update & Regression Sweep

**File:** `app/static/js/meeting.js`

**Implement:**
Update `setTransferButtonsState()` (~line 3002) to also disable/enable the new selectors:
```javascript
if (transfer.targetMode) {
    transfer.targetMode.disabled = disabled;
}
if (transfer.targetExistingActivity) {
    transfer.targetExistingActivity.disabled = disabled;
}
```

Also in `openTransferModal()` (~line 3533), after `transferState.active = true` and before `loadTransferBundles()`, call `onTransferModeChange()` to initialize UI visibility based on the default mode ("new"):
```javascript
onTransferModeChange();  // Initialize target selector visibility
```

**Canary verification:**
- Grep `meeting.js` for `Galactic Hamster` — should appear in the inline comments added in Steps 4, 5, 6.
- Grep `meeting.html` for `Galactic Hamster` — should appear in the HTML comment from Step 2.
- Grep `meeting.css` for `Galactic Hamster` — should appear in the CSS comment from Step 3.
- Grep source files for `Crimson Narwhal` — should only be in `transfer.py` (Phase 2).

**Test:** Run the full frontend smoke + transfer test suite:
```
pytest app/tests/test_frontend_smoke.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v
```
- `test_meeting_js_has_valid_syntax` must pass (proves no JS syntax errors introduced).
- All new Phase 3 smoke tests must pass.
- All Phase 1 + Phase 2 backend tests must still pass (no regressions from frontend changes).

**Docs:** No additional documentation beyond what was added in Steps 1-6.

**Technical Deviations Logged:**
- `meeting.js` initially had only two `Galactic Hamster` inline comments (Steps 4 and 6); added the missing Step 5 inline comment during Step 7 to satisfy canary verification expectations.
- `pytest` was not available on PATH in this shell, so all verification commands were executed via `venv/bin/pytest ...` (including the full-suite run).

---

## Phase Exit Criteria

The following command must pass at 100%:

```bash
pytest app/tests/test_frontend_smoke.py app/tests/test_transfer_api.py app/tests/test_transfer_metadata.py app/tests/test_transfer_transforms.py app/tests/test_transfer_comment_format_parity.py -v
```

**Specific assertions:**
- `test_meeting_js_has_valid_syntax` passes — no JS syntax errors (critical gate)
- `test_transfer_panel_has_target_mode_elements` passes — JS state fields present (Step 1)
- `test_transfer_panel_html_has_mode_selector` passes — HTML elements present (Step 2)
- `test_transfer_css_has_eligibility_hint_style` passes — CSS class present (Step 3)
- `test_transfer_js_has_mode_change_handler` passes — toggle functions present (Step 4)
- `test_transfer_js_has_existing_activity_builder` passes — dropdown builder and eligibility strings present (Step 5)
- `test_transfer_js_commit_handles_both_modes` passes — dual-mode commit logic present (Step 6)
- All pre-existing frontend smoke tests pass unchanged (Step 7)
- All Phase 1 + Phase 2 backend tests pass unchanged (Step 7)
- `Galactic Hamster` canary appears only in meeting.js, meeting.html, and meeting.css comments
