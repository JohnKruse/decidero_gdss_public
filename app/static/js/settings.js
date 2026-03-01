/**
 * settings.js — Admin/Facilitator Settings page
 *
 * Responsibilities:
 *   • Tab switching
 *   • Load current settings from GET /api/settings
 *   • Render field values + override-dot indicators
 *   • Track dirty state (unsaved changes)
 *   • Save sections via PUT /api/settings
 *   • Test AI connection via POST /api/settings/test-ai
 *   • API key / password show/replace/clear UI
 *   • Unsaved-changes warning on navigation
 */

'use strict';

(function () {

// ── State ────────────────────────────────────────────────────────────────────
let _settings = null;         // last payload from server
let _isAdmin  = false;        // role flag
let _dirty    = false;        // any unsaved field changes

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    _initTabs();
    _loadSettings();
    _initBeforeUnload();
});

// ── Tab navigation ───────────────────────────────────────────────────────────
function _initTabs() {
    const buttons = document.querySelectorAll('.settings-tab-btn');
    const panels  = document.querySelectorAll('.settings-tab-panel');
    buttons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.classList.contains('active')) return;
            if (_dirty && !confirm('You have unsaved changes. Leave this tab without saving?')) return;
            buttons.forEach(b => b.classList.remove('active'));
            panels.forEach(p => p.classList.remove('active'));
            btn.classList.add('active');
            const target = document.getElementById(btn.dataset.tab);
            if (target) target.classList.add('active');
        });
    });
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function _apiFetch(url, options = {}) {
    const resp = await fetch(url, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    if (!resp.ok) {
        let detail = `HTTP ${resp.status}`;
        try { detail = (await resp.json()).detail || detail; } catch (_) {}
        throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
    }
    return resp.json();
}

// ── Load ──────────────────────────────────────────────────────────────────────
async function _loadSettings() {
    _showPageLoading(true);
    try {
        _settings = await _apiFetch('/api/settings');
        _isAdmin  = _settings.is_admin;
        _renderAll();
        _dirty = false;
    } catch (err) {
        _showPageError('Failed to load settings: ' + err.message);
    } finally {
        _showPageLoading(false);
    }
}

function _showPageLoading(on) {
    const el = document.getElementById('settingsLoading');
    if (el) el.hidden = !on;
}
function _showPageError(msg) {
    const el = document.getElementById('settingsPageError');
    if (el) { el.textContent = msg; el.hidden = false; }
}

// ── Render ────────────────────────────────────────────────────────────────────
function _renderAll() {
    if (!_settings) return;
    _renderAiTab();
    _renderMeetingsTab();
    _renderBrainstormingTab();
    _renderSecurityTab();
}

function _setField(id, value) {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.type === 'checkbox') {
        el.checked = Boolean(value);
    } else {
        el.value = value ?? '';
    }
}

function _setOverrideDot(fieldId, hasOverride) {
    const dot = document.querySelector(`[data-dot="${fieldId}"]`);
    if (dot) dot.hidden = !hasOverride;
}

function _markOverrides(section, keys) {
    const overrides = _settings.db_overrides || {};
    keys.forEach(({ fieldId, dbKey }) => {
        _setOverrideDot(fieldId, Boolean(overrides[dbKey]));
    });
}

// ── AI tab ────────────────────────────────────────────────────────────────────
function _renderAiTab() {
    const ai = _settings.ai;
    const overrides = _settings.db_overrides || {};
    const isAdmin = _isAdmin;

    _setField('ai-provider', ai.provider);
    _setField('ai-model', ai.model);
    _setField('ai-endpoint-url', ai.endpoint_url);
    _setField('ai-max-tokens', ai.max_tokens);
    _setField('ai-temperature', ai.temperature);

    // API key: show preview row or replace field
    _renderSecretField({
        previewRowId:    'ai-key-preview-row',
        previewTextId:   'ai-key-preview-text',
        replaceWrapperId:'ai-key-replace-wrapper',
        inputId:         'ai-key-input',
        replaceBtnId:    'ai-key-replace-btn',
        clearBtnId:      'ai-key-clear-btn',
        isSet:           ai.api_key_set,
        preview:         ai.api_key_preview,
        disabled:        !isAdmin,
    });

    // AI status badge
    const statusRow  = document.getElementById('ai-status-row');
    const statusDot  = document.getElementById('ai-status-dot');
    const statusText = document.getElementById('ai-status-text');
    if (statusRow) {
        const ok = ai.enabled;
        statusDot.className  = 'status-dot ' + (ok ? 'ok' : 'warn');
        statusText.textContent = ok
            ? `Connected — ${ai.provider} / ${ai.model}`
            : 'Not configured — enter provider, API key, and model below.';
    }

    // Override dots
    [
        { fieldId: 'ai-provider',     dbKey: 'ai.provider'     },
        { fieldId: 'ai-key-input',    dbKey: 'ai.api_key'      },
        { fieldId: 'ai-endpoint-url', dbKey: 'ai.endpoint_url' },
        { fieldId: 'ai-model',        dbKey: 'ai.model'        },
        { fieldId: 'ai-max-tokens',   dbKey: 'ai.max_tokens'   },
        { fieldId: 'ai-temperature',  dbKey: 'ai.temperature'  },
    ].forEach(({ fieldId, dbKey }) => _setOverrideDot(fieldId, Boolean(overrides[dbKey])));

    // Show/hide endpoint URL based on provider
    _toggleEndpointUrl(ai.provider);
    const providerSel = document.getElementById('ai-provider');
    if (providerSel) {
        providerSel.addEventListener('change', () => _toggleEndpointUrl(providerSel.value));
    }

    _watchDirty('ai-provider', 'ai-model', 'ai-endpoint-url', 'ai-max-tokens', 'ai-temperature');
}

function _toggleEndpointUrl(provider) {
    const row = document.getElementById('ai-endpoint-url-row');
    if (!row) return;
    row.hidden = provider !== 'openai_compatible';
}

// ── Meetings tab ──────────────────────────────────────────────────────────────
function _renderMeetingsTab() {
    const m = _settings.meetings;
    const overrides = _settings.db_overrides || {};

    _setField('meetings-max-participants',           m.max_participants);
    _setField('meetings-recording-enabled',          m.recording_enabled);
    _setField('meetings-participant-exclusivity',     m.activity_participant_exclusivity);
    _setField('meetings-allow-guest-join',           m.allow_guest_join);
    _setField('meetings-session-expire',             m.access_token_expire_minutes);

    _renderSecretField({
        previewRowId:    'meetings-password-preview-row',
        previewTextId:   'meetings-password-preview-text',
        replaceWrapperId:'meetings-password-replace-wrapper',
        inputId:         'meetings-password-input',
        replaceBtnId:    'meetings-password-replace-btn',
        clearBtnId:      'meetings-password-clear-btn',
        isSet:           m.default_user_password_set,
        preview:         m.default_user_password_preview,
        disabled:        !_isAdmin,
    });

    [
        { fieldId: 'meetings-max-participants',       dbKey: 'meetings.max_participants'              },
        { fieldId: 'meetings-recording-enabled',      dbKey: 'meetings.recording_enabled'             },
        { fieldId: 'meetings-participant-exclusivity',dbKey: 'meetings.activity_participant_exclusivity'},
        { fieldId: 'meetings-allow-guest-join',       dbKey: 'meetings.allow_guest_join'              },
        { fieldId: 'meetings-session-expire',         dbKey: 'meetings.access_token_expire_minutes'   },
        { fieldId: 'meetings-password-input',         dbKey: 'meetings.default_user_password'         },
    ].forEach(({ fieldId, dbKey }) => _setOverrideDot(fieldId, Boolean(overrides[dbKey])));

    _watchDirty('meetings-max-participants', 'meetings-session-expire');
    _watchDirtyCheckbox('meetings-recording-enabled', 'meetings-participant-exclusivity', 'meetings-allow-guest-join');
}

// ── Brainstorming tab ─────────────────────────────────────────────────────────
function _renderBrainstormingTab() {
    const b = _settings.brainstorming;
    const overrides = _settings.db_overrides || {};

    _setField('bs-char-limit',       b.idea_character_limit);
    _setField('bs-max-ideas',        b.max_ideas_per_user);
    _setField('bs-anonymity',        b.default_maintain_anonymity);
    _setField('bs-subcomments',      b.default_allow_subcomments);
    _setField('bs-auto-jump',        b.default_auto_jump_new_ideas);

    [
        { fieldId: 'bs-char-limit',  dbKey: 'brainstorming.idea_character_limit'       },
        { fieldId: 'bs-max-ideas',   dbKey: 'brainstorming.max_ideas_per_user'         },
        { fieldId: 'bs-anonymity',   dbKey: 'brainstorming.default_maintain_anonymity' },
        { fieldId: 'bs-subcomments', dbKey: 'brainstorming.default_allow_subcomments'  },
        { fieldId: 'bs-auto-jump',   dbKey: 'brainstorming.default_auto_jump_new_ideas'},
    ].forEach(({ fieldId, dbKey }) => _setOverrideDot(fieldId, Boolean(overrides[dbKey])));

    _watchDirty('bs-char-limit', 'bs-max-ideas');
    _watchDirtyCheckbox('bs-anonymity', 'bs-subcomments', 'bs-auto-jump');
}

// ── Security tab ──────────────────────────────────────────────────────────────
function _renderSecurityTab() {
    const s = _settings.security;
    const overrides = _settings.db_overrides || {};

    _setField('sec-rate-limit-enabled',       s.login_rate_limit_enabled);
    _setField('sec-rate-limit-window',        s.login_rate_limit_window_seconds);
    _setField('sec-rate-limit-max-user',      s.login_rate_limit_max_failures_per_username);
    _setField('sec-rate-limit-max-ip',        s.login_rate_limit_max_failures_per_ip);
    _setField('sec-rate-limit-lockout',       s.login_rate_limit_lockout_seconds);

    [
        { fieldId: 'sec-rate-limit-enabled',  dbKey: 'security.login_rate_limit_enabled'                    },
        { fieldId: 'sec-rate-limit-window',   dbKey: 'security.login_rate_limit_window_seconds'             },
        { fieldId: 'sec-rate-limit-max-user', dbKey: 'security.login_rate_limit_max_failures_per_username'  },
        { fieldId: 'sec-rate-limit-max-ip',   dbKey: 'security.login_rate_limit_max_failures_per_ip'        },
        { fieldId: 'sec-rate-limit-lockout',  dbKey: 'security.login_rate_limit_lockout_seconds'            },
    ].forEach(({ fieldId, dbKey }) => _setOverrideDot(fieldId, Boolean(overrides[dbKey])));

    _toggleRateLimitSubfields(s.login_rate_limit_enabled);
    const masterToggle = document.getElementById('sec-rate-limit-enabled');
    if (masterToggle) {
        masterToggle.addEventListener('change', () => {
            _toggleRateLimitSubfields(masterToggle.checked);
        });
    }

    _watchDirty('sec-rate-limit-window', 'sec-rate-limit-max-user', 'sec-rate-limit-max-ip', 'sec-rate-limit-lockout');
    _watchDirtyCheckbox('sec-rate-limit-enabled');
}

function _toggleRateLimitSubfields(enabled) {
    const subfields = document.querySelectorAll('.sec-rate-subfield');
    subfields.forEach(el => {
        el.disabled = !enabled;
    });
}

// ── Secret field (API key / password) ────────────────────────────────────────
function _renderSecretField({ previewRowId, previewTextId, replaceWrapperId,
                               inputId, replaceBtnId, clearBtnId,
                               isSet, preview, disabled }) {
    const previewRow     = document.getElementById(previewRowId);
    const previewText    = document.getElementById(previewTextId);
    const replaceWrapper = document.getElementById(replaceWrapperId);
    const input          = document.getElementById(inputId);
    const replaceBtn     = document.getElementById(replaceBtnId);
    const clearBtn       = document.getElementById(clearBtnId);

    if (!previewRow || !replaceWrapper || !input) return;

    const show = () => {
        previewRow.hidden    = false;
        replaceWrapper.hidden = true;
        if (input) input.value = '';
    };
    const showReplace = () => {
        previewRow.hidden    = true;
        replaceWrapper.hidden = false;
        if (input) { input.value = ''; input.focus(); }
    };

    if (isSet) {
        if (previewText) previewText.textContent = preview;
        show();
    } else {
        previewRow.hidden    = true;
        replaceWrapper.hidden = false;
    }

    if (disabled) {
        if (input) input.disabled = true;
        if (replaceBtn) replaceBtn.disabled = true;
        if (clearBtn)   clearBtn.disabled   = true;
        return;
    }

    if (replaceBtn) {
        replaceBtn.addEventListener('click', showReplace);
    }
    if (clearBtn) {
        clearBtn.addEventListener('click', () => {
            if (!confirm('Remove the current value? The feature will use config.yaml default (or be disabled) until a new value is saved.')) return;
            if (input) input.value = '';     // empty string signals "clear" to the API
            previewRow.hidden     = true;
            replaceWrapper.hidden = false;
            _markDirty();
        });
    }
    // Typing in the replace field counts as dirty
    if (input) input.addEventListener('input', _markDirty);
}

// ── Dirty tracking ────────────────────────────────────────────────────────────
function _watchDirty(...ids) {
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', _markDirty);
    });
}
function _watchDirtyCheckbox(...ids) {
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', _markDirty);
    });
}
function _markDirty() {
    _dirty = true;
}
function _clearDirty() {
    _dirty = false;
}

function _initBeforeUnload() {
    window.addEventListener('beforeunload', e => {
        if (!_dirty) return;
        e.preventDefault();
        e.returnValue = '';
    });
}

// ── Save handlers (called from HTML onclick) ───────────────────────────────────
window.saveAiSettings = async function () {
    if (!_isAdmin) return;
    const payload = {};

    const provider    = _val('ai-provider');
    const model       = _val('ai-model');
    const endpointUrl = _val('ai-endpoint-url');
    const maxTokens   = parseInt(_val('ai-max-tokens'), 10);
    const temperature = parseFloat(_val('ai-temperature'));
    const keyInput    = document.getElementById('ai-key-input');
    const keyVal      = keyInput && !keyInput.disabled && !document.getElementById('ai-key-replace-wrapper')?.hidden
                        ? keyInput.value.trim()
                        : null;

    if (provider)    payload['ai.provider']     = provider;
    if (model)       payload['ai.model']        = model;
    payload['ai.endpoint_url'] = endpointUrl;   // can be blank (valid)
    if (!isNaN(maxTokens) && maxTokens > 0)     payload['ai.max_tokens']   = maxTokens;
    if (!isNaN(temperature))                    payload['ai.temperature']  = temperature;
    if (keyVal !== null)                        payload['ai.api_key']      = keyVal;

    await _saveSection('ai-feedback', payload);
};

window.saveMeetingsSettings = async function () {
    if (!_isAdmin) return;
    const payload = {};

    payload['meetings.max_participants']            = parseInt(_val('meetings-max-participants'), 10);
    payload['meetings.recording_enabled']           = _checked('meetings-recording-enabled');
    payload['meetings.activity_participant_exclusivity'] = _checked('meetings-participant-exclusivity');
    payload['meetings.allow_guest_join']            = _checked('meetings-allow-guest-join');
    payload['meetings.access_token_expire_minutes'] = parseInt(_val('meetings-session-expire'), 10);

    const pwInput = document.getElementById('meetings-password-input');
    const pwWrapper = document.getElementById('meetings-password-replace-wrapper');
    if (pwInput && pwWrapper && !pwWrapper.hidden) {
        payload['meetings.default_user_password'] = pwInput.value;
    }

    await _saveSection('meetings-feedback', payload);
};

window.saveBrainstormingSettings = async function () {
    const payload = {
        'brainstorming.idea_character_limit':       parseInt(_val('bs-char-limit'), 10),
        'brainstorming.max_ideas_per_user':         parseInt(_val('bs-max-ideas'), 10),
        'brainstorming.default_maintain_anonymity': _checked('bs-anonymity'),
        'brainstorming.default_allow_subcomments':  _checked('bs-subcomments'),
        'brainstorming.default_auto_jump_new_ideas':_checked('bs-auto-jump'),
    };
    await _saveSection('brainstorming-feedback', payload);
};

window.saveSecuritySettings = async function () {
    if (!_isAdmin) return;
    const payload = {
        'security.login_rate_limit_enabled':                   _checked('sec-rate-limit-enabled'),
        'security.login_rate_limit_window_seconds':            parseInt(_val('sec-rate-limit-window'),   10),
        'security.login_rate_limit_max_failures_per_username': parseInt(_val('sec-rate-limit-max-user'), 10),
        'security.login_rate_limit_max_failures_per_ip':       parseInt(_val('sec-rate-limit-max-ip'),   10),
        'security.login_rate_limit_lockout_seconds':           parseInt(_val('sec-rate-limit-lockout'),  10),
    };
    await _saveSection('security-feedback', payload);
};

async function _saveSection(feedbackId, payload) {
    const fb = document.getElementById(feedbackId);
    _setFeedback(fb, 'info', 'Saving…');
    try {
        _settings = await _apiFetch('/api/settings', {
            method: 'PUT',
            body: JSON.stringify({ settings: payload }),
        });
        _isAdmin = _settings.is_admin;
        _renderAll();
        _clearDirty();
        _setFeedback(fb, 'success', 'Settings saved.');
        setTimeout(() => _setFeedback(fb, '', ''), 4000);
    } catch (err) {
        _setFeedback(fb, 'error', 'Save failed: ' + err.message);
    }
}

// ── Test AI connection ────────────────────────────────────────────────────────
window.testAiConnection = async function () {
    const resultEl  = document.getElementById('ai-test-result');
    const btn       = document.getElementById('ai-test-btn');
    if (!resultEl || !btn) return;

    const provider    = _val('ai-provider');
    const model       = _val('ai-model');
    const endpointUrl = _val('ai-endpoint-url');

    // API key: prefer what's typed in the replace field; fall back to "use stored"
    const keyWrapper = document.getElementById('ai-key-replace-wrapper');
    const keyInput   = document.getElementById('ai-key-input');
    const useNewKey  = keyWrapper && !keyWrapper.hidden && keyInput && keyInput.value.trim();
    const apiKey     = useNewKey ? keyInput.value.trim() : '__stored__';

    if (!provider || !model) {
        _showTestResult(resultEl, false, 'Provider and Model are required.');
        return;
    }
    if (!useNewKey && !(_settings && _settings.ai && _settings.ai.api_key_set)) {
        _showTestResult(resultEl, false, 'No API key set. Enter a new key in the field above.');
        return;
    }

    btn.disabled = true;
    resultEl.innerHTML = '<span class="spinner"></span> Testing…';
    resultEl.className = 'settings-feedback info';

    try {
        const resp = await _apiFetch('/api/settings/test-ai', {
            method: 'POST',
            body: JSON.stringify({
                provider,
                api_key: apiKey === '__stored__' ? (_settings.ai._raw_key_placeholder || 'STORED') : apiKey,
                endpoint_url: endpointUrl,
                model,
            }),
        });
        if (resp.success) {
            _showTestResult(resultEl, true, `Connected — ${resp.latency_ms}ms`);
        } else {
            _showTestResult(resultEl, false, resp.error || 'Connection failed.');
        }
    } catch (err) {
        _showTestResult(resultEl, false, err.message);
    } finally {
        btn.disabled = false;
    }
};

function _showTestResult(el, ok, msg) {
    el.className = ok ? 'test-result ok' : 'test-result err';
    el.innerHTML = (ok ? '✓ ' : '✗ ') + _escapeHtml(msg);
}

// ── Tiny helpers ──────────────────────────────────────────────────────────────
function _val(id)     { const el = document.getElementById(id); return el ? el.value : ''; }
function _checked(id) { const el = document.getElementById(id); return el ? el.checked : false; }

function _setFeedback(el, type, msg) {
    if (!el) return;
    el.textContent = msg;
    el.className   = 'settings-feedback ' + type;
}

function _escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

})();
