/**
 * settings.js — Admin/Facilitator Settings page
 * Version 3 — Per-provider card UI
 *
 * Responsibilities:
 *   • Tab switching
 *   • Load current settings from GET /api/settings
 *   • Render 5 provider cards (one per AI provider)
 *   • Per-card: Save key+model, Delete key, Test connection, Load models
 *   • Radio button → auto-saves active_provider
 *   • Shared AI param section (max_tokens, temperature)
 *   • Meeting, Brainstorming, Security tabs (unchanged from v2)
 */

'use strict';

(function () {

// ── Provider config ───────────────────────────────────────────────────────────
const _PROVIDERS = [
    { slug: 'anthropic',         label: 'Anthropic (Claude)',  canFetchModels: true  },
    { slug: 'openai',            label: 'OpenAI (GPT)',        canFetchModels: true  },
    { slug: 'google',            label: 'Google (Gemini)',     canFetchModels: true  },
    { slug: 'openrouter',        label: 'OpenRouter',          canFetchModels: true  },
    { slug: 'openai_compatible', label: 'OpenAI-Compatible',   canFetchModels: false },
];

// ── State ─────────────────────────────────────────────────────────────────────
let _settings = null;   // last payload from GET /api/settings
let _isAdmin  = false;
let _dirty    = false;

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    _initTabs();
    _loadSettings();
    _initBeforeUnload();
});

// ── Tab navigation ────────────────────────────────────────────────────────────
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

// ── Render all tabs ────────────────────────────────────────────────────────────
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

// selector: full CSS selector, e.g. '[data-dot="field-id"]' or '[data-key="ai.max_tokens"]'
function _setOverrideDot(selector, hasOverride) {
    const dot = document.querySelector(selector);
    if (dot) dot.hidden = !hasOverride;
}

// ══════════════════════════════════════════════════════════════════════════════
// AI TAB — Provider cards
// ══════════════════════════════════════════════════════════════════════════════

function _renderAiTab() {
    if (!_settings || !_settings.ai) return;
    const ai       = _settings.ai;
    const overrides = _settings.db_overrides || {};
    const active   = ai.active_provider || '';
    const providers = ai.providers || {};

    // Render provider cards
    const container = document.getElementById('provider-cards-container');
    if (container) {
        container.innerHTML = _PROVIDERS.map(p =>
            _buildCardHtml(p, providers[p.slug] || {}, active)
        ).join('');
        _PROVIDERS.forEach(p => _attachCardListeners(p.slug));
    }

    // Show & populate the shared generation params section
    const sharedSection = document.getElementById('ai-shared-params-section');
    if (sharedSection) sharedSection.hidden = false;

    _setField('ai-max-tokens',  ai.max_tokens);
    _setField('ai-temperature', ai.temperature);

    _setOverrideDot('[data-key="ai.max_tokens"]',  Boolean(overrides['ai.max_tokens']));
    _setOverrideDot('[data-key="ai.temperature"]', Boolean(overrides['ai.temperature']));

    _watchDirty('ai-max-tokens', 'ai-temperature');
}

// ── Build card HTML ───────────────────────────────────────────────────────────
function _buildCardHtml(provider, data, activeProvider) {
    const slug     = provider.slug;
    const label    = provider.label;
    const isActive = (activeProvider === slug);
    const isSet    = data.api_key_set || false;
    const preview  = data.api_key_preview || '';
    const model    = data.model || '';
    const disabled = !_isAdmin;

    const cardClass = ['provider-card', isActive ? 'active' : '', !isSet ? 'unconfigured' : '']
        .filter(Boolean).join(' ');

    // ── API key row
    let keyHtml;
    if (isSet) {
        keyHtml = `
        <div class="card-api-key-row">
          <span class="card-field-label">API Key</span>
          <div class="card-key-preview">
            <span class="card-key-preview-text">${_escapeHtml(preview)}</span>
            ${!disabled
                ? `<button class="btn-card-delete" type="button"
                      onclick="deleteProviderKey('${slug}')" title="Remove stored key">✕</button>`
                : ''}
          </div>
        </div>`;
    } else {
        keyHtml = `
        <div class="card-api-key-row">
          <span class="card-field-label">API Key</span>
          <input class="card-key-input" type="password" id="card-key-${slug}"
                 placeholder="Paste API key…" autocomplete="new-password"
                 ${disabled ? 'disabled' : ''}>
        </div>`;
    }

    // ── Endpoint URL (openai_compatible only)
    const endpointHtml = (slug === 'openai_compatible') ? `
        <div class="card-endpoint-row">
          <span class="card-field-label">Endpoint URL</span>
          <input class="card-endpoint-input" type="url" id="card-endpoint-${slug}"
                 value="${_escapeHtml(data.endpoint_url || '')}"
                 placeholder="https://your-endpoint/v1"
                 ${disabled ? 'disabled' : ''}>
          <span style="font-size:.72rem;color:var(--silver);margin-top:.2rem;display:block">
            Azure: <code>https://&lt;resource&gt;.openai.azure.com/openai/deployments/&lt;deployment&gt;/chat/completions?api-version=2024-02-01</code>
            &nbsp;·&nbsp; Ollama: <code>http://localhost:11434/v1</code>
          </span>
        </div>` : '';

    // ── Model row (text input; select added dynamically after Load Models)
    const modelHtml = `
        <div class="card-model-row">
          <span class="card-field-label">Model</span>
          <div id="card-model-select-wrap-${slug}" hidden>
            <select class="card-model-select" id="card-model-select-${slug}"
                    ${disabled ? 'disabled' : ''}></select>
          </div>
          <div id="card-model-text-wrap-${slug}">
            <input class="card-model-input" type="text" id="card-model-${slug}"
                   value="${_escapeHtml(model)}"
                   placeholder="e.g. claude-opus-4-5, gpt-4o…"
                   ${disabled ? 'disabled' : ''}>
          </div>
          ${!disabled
              ? `<button class="card-model-manual-link" type="button"
                     id="card-model-manual-link-${slug}" hidden
                     onclick="cardShowTextInput('${slug}')">← Enter model ID manually</button>`
              : ''}
        </div>`;

    // ── Action row
    const actionsHtml = !disabled ? `
        <div class="card-actions">
          <button class="btn-card-save" type="button"
                  onclick="saveCardSettings('${slug}')">SAVE</button>
          ${provider.canFetchModels
              ? `<button class="btn-card-fetch" type="button" id="card-fetch-btn-${slug}"
                         onclick="fetchModelsForCard('${slug}')">↻ Load Models</button>`
              : ''}
          <button class="btn-card-test" type="button" id="card-test-btn-${slug}"
                  onclick="testConnectionForCard('${slug}')">▷ Test</button>
          <span class="card-test-result" id="card-test-result-${slug}"></span>
          <span class="settings-feedback" id="card-feedback-${slug}"
                style="margin-left:auto;font-size:.75rem"></span>
        </div>` : '';

    return `
  <div class="${cardClass}" id="provider-card-${slug}" data-slug="${slug}">
    <div class="provider-card-header">
      <input type="radio" name="active-provider" id="radio-${slug}"
             value="${slug}" ${isActive ? 'checked' : ''}
             ${disabled || !isSet ? 'disabled' : ''}>
      <label class="provider-radio-label" for="radio-${slug}">
        <span class="provider-name">${_escapeHtml(label)}</span>
      </label>
      <span class="${isSet ? 'card-status-chip set' : 'card-status-chip unset'}">
        ${isSet ? '✓ Configured' : 'Not set'}
      </span>
    </div>
    ${keyHtml}
    ${endpointHtml}
    ${modelHtml}
    ${actionsHtml}
  </div>`;
}

// ── Attach listeners to a freshly rendered card ───────────────────────────────
function _attachCardListeners(slug) {
    // Radio → set as active provider
    const radio = document.getElementById(`radio-${slug}`);
    if (radio) {
        radio.addEventListener('change', () => {
            if (radio.checked) setActiveProvider(slug);
        });
    }

    // Model select → sync value to hidden text input / switch to manual mode
    const modelSelect = document.getElementById(`card-model-select-${slug}`);
    if (modelSelect) {
        modelSelect.addEventListener('change', () => {
            if (modelSelect.value === '__manual__') {
                cardShowTextInput(slug);
            } else if (modelSelect.value) {
                const ti = document.getElementById(`card-model-${slug}`);
                if (ti) ti.value = modelSelect.value;
                _markDirty();
            }
        });
    }

    // Dirty tracking for text inputs on the card
    [`card-key-${slug}`, `card-model-${slug}`, `card-endpoint-${slug}`].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', _markDirty);
    });
}

// Expose to inline onclick handlers
window.cardShowTextInput = function (slug) {
    const selWrap = document.getElementById(`card-model-select-wrap-${slug}`);
    const txtWrap = document.getElementById(`card-model-text-wrap-${slug}`);
    const link    = document.getElementById(`card-model-manual-link-${slug}`);
    if (selWrap) selWrap.hidden = true;
    if (txtWrap) txtWrap.hidden = false;
    if (link)    link.hidden    = true;
};

// ── Save card (key + model + endpoint) ───────────────────────────────────────
window.saveCardSettings = async function (slug) {
    if (!_isAdmin) return;
    const fbEl = document.getElementById(`card-feedback-${slug}`);
    _setFeedback(fbEl, 'info', 'Saving…');

    const payload = {};

    // New API key (only present when the key input is shown and non-empty)
    const keyInput = document.getElementById(`card-key-${slug}`);
    if (keyInput && keyInput.value.trim()) {
        payload[`ai.${slug}.api_key`] = keyInput.value.trim();
    }

    // Model: prefer active select value, else text input
    const selWrap  = document.getElementById(`card-model-select-wrap-${slug}`);
    const select   = document.getElementById(`card-model-select-${slug}`);
    const textInput = document.getElementById(`card-model-${slug}`);
    let modelVal = '';
    if (selWrap && !selWrap.hidden && select && select.value && select.value !== '__manual__') {
        modelVal = select.value;
    } else if (textInput) {
        modelVal = textInput.value.trim();
    }
    if (modelVal) payload[`ai.${slug}.model`] = modelVal;

    // Endpoint URL (openai_compatible only)
    if (slug === 'openai_compatible') {
        const epInput = document.getElementById(`card-endpoint-${slug}`);
        if (epInput) payload['ai.openai_compatible.endpoint_url'] = epInput.value.trim();
    }

    if (Object.keys(payload).length === 0) {
        _setFeedback(fbEl, 'error', 'Nothing to save.');
        return;
    }

    try {
        _settings = await _apiFetch('/api/settings', {
            method: 'PUT',
            body: JSON.stringify({ settings: payload }),
        });
        _isAdmin = _settings.is_admin;
        _renderAll();          // rebuilds all cards from server state
        _clearDirty();
        // Re-find the feedback element (DOM was just rebuilt)
        const newFb = document.getElementById(`card-feedback-${slug}`);
        _setFeedback(newFb, 'success', '✓ Saved');
        setTimeout(() => _setFeedback(document.getElementById(`card-feedback-${slug}`), '', ''), 3000);
    } catch (err) {
        const fb2 = document.getElementById(`card-feedback-${slug}`);
        _setFeedback(fb2 || fbEl, 'error', '✗ ' + err.message);
    }
};

// ── Delete provider key ───────────────────────────────────────────────────────
window.deleteProviderKey = async function (slug) {
    if (!_isAdmin) return;
    const provLabel = _PROVIDERS.find(p => p.slug === slug)?.label || slug;
    if (!confirm(`Remove the stored API key for ${provLabel}? This provider will be unavailable until you save a new key.`)) return;

    const fbEl = document.getElementById(`card-feedback-${slug}`);
    _setFeedback(fbEl, 'info', 'Removing key…');
    try {
        const resp = await fetch(`/api/settings/ai.${slug}.api_key`, {
            method: 'DELETE',
            credentials: 'include',
        });
        if (!resp.ok) {
            let detail = `HTTP ${resp.status}`;
            try { detail = (await resp.json()).detail || detail; } catch (_) {}
            throw new Error(detail);
        }
        _settings = await resp.json();
        _isAdmin  = _settings.is_admin;
        _renderAll();
    } catch (err) {
        const fb2 = document.getElementById(`card-feedback-${slug}`);
        _setFeedback(fb2 || fbEl, 'error', '✗ ' + err.message);
    }
};

// ── Set active provider ───────────────────────────────────────────────────────
window.setActiveProvider = async function (slug) {
    if (!_isAdmin) return;
    try {
        _settings = await _apiFetch('/api/settings', {
            method: 'PUT',
            body: JSON.stringify({ settings: { 'ai.active_provider': slug } }),
        });
        _isAdmin = _settings.is_admin;
        _renderAll();
    } catch (err) {
        console.error('Failed to set active provider:', err.message);
    }
};

// ── Fetch models for a card ───────────────────────────────────────────────────
window.fetchModelsForCard = async function (slug) {
    if (!_isAdmin) return;
    const fbEl = document.getElementById(`card-feedback-${slug}`);
    const btn  = document.getElementById(`card-fetch-btn-${slug}`);

    // API key: prefer newly-typed value; otherwise use stored sentinel
    const keyInput = document.getElementById(`card-key-${slug}`);
    const newKey   = keyInput && keyInput.value.trim();
    const apiKey   = newKey || '__stored__';

    const provData = _settings?.ai?.providers?.[slug];
    if (!newKey && !provData?.api_key_set) {
        _setFeedback(fbEl, 'error', 'No API key saved — enter and save a key first.');
        return;
    }

    if (btn) btn.disabled = true;
    _setFeedback(fbEl, 'info', '↻ Fetching models…');

    try {
        let url = `/api/settings/models?provider=${encodeURIComponent(slug)}&api_key=${encodeURIComponent(apiKey)}`;
        const epInput = document.getElementById(`card-endpoint-${slug}`);
        if (epInput && epInput.value.trim()) {
            url += `&endpoint_url=${encodeURIComponent(epInput.value.trim())}`;
        }

        const data   = await _apiFetch(url);
        const models = data.models || [];

        if (models.length === 0) {
            _setFeedback(fbEl, 'info', 'No suitable chat models found for this key.');
            return;
        }

        _buildCardModelSelect(slug, models);
        _setFeedback(fbEl, 'success', `✓ ${models.length} models`);
        setTimeout(() => _setFeedback(document.getElementById(`card-feedback-${slug}`), '', ''), 4000);

    } catch (err) {
        _setFeedback(fbEl, 'error', '✗ ' + err.message);
    } finally {
        if (btn) btn.disabled = false;
    }
};

function _buildCardModelSelect(slug, models) {
    const select  = document.getElementById(`card-model-select-${slug}`);
    const txtWrap = document.getElementById(`card-model-text-wrap-${slug}`);
    const selWrap = document.getElementById(`card-model-select-wrap-${slug}`);
    const txtInput = document.getElementById(`card-model-${slug}`);
    const manLink  = document.getElementById(`card-model-manual-link-${slug}`);
    if (!select) return;

    const currentModel = txtInput ? txtInput.value.trim() : '';
    select.innerHTML = '';

    // Prepend current model if not in fetched list
    if (currentModel && !models.includes(currentModel)) {
        const opt = document.createElement('option');
        opt.value = currentModel;
        opt.textContent = `${currentModel} (current)`;
        opt.selected = true;
        select.appendChild(opt);
    }

    models.forEach(m => {
        const opt = document.createElement('option');
        opt.value = m;
        opt.textContent = m;
        if (m === currentModel) opt.selected = true;
        select.appendChild(opt);
    });

    // "Enter manually" escape hatch
    const manualOpt = document.createElement('option');
    manualOpt.value = '__manual__';
    manualOpt.textContent = '✏ Enter model ID manually…';
    select.appendChild(manualOpt);

    // If nothing pre-selected, auto-select first model
    if (!currentModel && models.length > 0) {
        select.selectedIndex = 0;
        if (txtInput) txtInput.value = models[0];
        _markDirty();
    }

    if (selWrap) selWrap.hidden = false;
    if (txtWrap) txtWrap.hidden = true;
    if (manLink) manLink.hidden = false;
}

// ── Test connection for a card ────────────────────────────────────────────────
window.testConnectionForCard = async function (slug) {
    if (!_isAdmin) return;
    const resultEl = document.getElementById(`card-test-result-${slug}`);
    const btn      = document.getElementById(`card-test-btn-${slug}`);

    // Resolve model
    const selWrap  = document.getElementById(`card-model-select-wrap-${slug}`);
    const select   = document.getElementById(`card-model-select-${slug}`);
    const txtInput = document.getElementById(`card-model-${slug}`);
    let model = '';
    if (selWrap && !selWrap.hidden && select && select.value && select.value !== '__manual__') {
        model = select.value;
    } else if (txtInput) {
        model = txtInput.value.trim();
    }

    // Resolve API key
    const keyInput = document.getElementById(`card-key-${slug}`);
    const newKey   = keyInput && keyInput.value.trim();
    const apiKey   = newKey || '__stored__';

    const provData = _settings?.ai?.providers?.[slug];
    if (!newKey && !provData?.api_key_set) {
        _cardTestResult(resultEl, false, 'No key set');
        return;
    }
    if (!model) {
        _cardTestResult(resultEl, false, 'No model');
        return;
    }

    if (btn) btn.disabled = true;
    if (resultEl) {
        resultEl.className   = 'card-test-result';
        resultEl.innerHTML   = '<span class="spinner"></span>';
    }

    const epInput    = document.getElementById(`card-endpoint-${slug}`);
    const endpointUrl = epInput ? epInput.value.trim() : '';

    try {
        const resp = await _apiFetch('/api/settings/test-ai', {
            method: 'POST',
            body: JSON.stringify({ provider: slug, api_key: apiKey, endpoint_url: endpointUrl, model }),
        });
        _cardTestResult(resultEl, resp.success, resp.success ? `✓ ${resp.latency_ms}ms` : (resp.error || 'Failed'));
    } catch (err) {
        _cardTestResult(resultEl, false, err.message);
    } finally {
        if (btn) btn.disabled = false;
    }
};

function _cardTestResult(el, ok, msg) {
    if (!el) return;
    el.className   = ok ? 'card-test-result ok' : 'card-test-result err';
    el.textContent = (ok ? '✓ ' : '✗ ') + msg;
}

// ── Save shared AI params (max_tokens, temperature) ──────────────────────────
window.saveAiSharedParams = async function () {
    if (!_isAdmin) return;
    const payload = {};
    const maxTokens   = parseInt(_val('ai-max-tokens'), 10);
    const temperature = parseFloat(_val('ai-temperature'));
    if (!isNaN(maxTokens) && maxTokens > 0) payload['ai.max_tokens']  = maxTokens;
    if (!isNaN(temperature))                payload['ai.temperature'] = temperature;
    await _saveSection('ai-params-feedback', payload);
};

// ══════════════════════════════════════════════════════════════════════════════
// MEETINGS TAB
// ══════════════════════════════════════════════════════════════════════════════

function _renderMeetingsTab() {
    const m        = _settings.meetings;
    const overrides = _settings.db_overrides || {};

    _setField('meetings-max-participants',        m.max_participants);
    _setField('meetings-recording-enabled',       m.recording_enabled);
    _setField('meetings-participant-exclusivity', m.activity_participant_exclusivity);
    _setField('meetings-allow-guest-join',        m.allow_guest_join);
    _setField('meetings-session-expire',          m.access_token_expire_minutes);

    _renderSecretField({
        previewRowId:     'meetings-password-preview-row',
        previewTextId:    'meetings-password-preview-text',
        replaceWrapperId: 'meetings-password-replace-wrapper',
        inputId:          'meetings-password-input',
        replaceBtnId:     'meetings-password-replace-btn',
        clearBtnId:       'meetings-password-clear-btn',
        isSet:            m.default_user_password_set,
        preview:          m.default_user_password_preview,
        disabled:         !_isAdmin,
    });

    [
        { dot: 'meetings-max-participants',        key: 'meetings.max_participants'                },
        { dot: 'meetings-recording-enabled',       key: 'meetings.recording_enabled'               },
        { dot: 'meetings-participant-exclusivity', key: 'meetings.activity_participant_exclusivity' },
        { dot: 'meetings-allow-guest-join',        key: 'meetings.allow_guest_join'                },
        { dot: 'meetings-session-expire',          key: 'meetings.access_token_expire_minutes'     },
        { dot: 'meetings-password-input',          key: 'meetings.default_user_password'           },
    ].forEach(({ dot, key }) => _setOverrideDot(`[data-dot="${dot}"]`, Boolean(overrides[key])));

    _watchDirty('meetings-max-participants', 'meetings-session-expire');
    _watchDirtyCheckbox('meetings-recording-enabled', 'meetings-participant-exclusivity', 'meetings-allow-guest-join');
}

window.saveMeetingsSettings = async function () {
    if (!_isAdmin) return;
    const payload = {
        'meetings.max_participants':             parseInt(_val('meetings-max-participants'), 10),
        'meetings.recording_enabled':            _checked('meetings-recording-enabled'),
        'meetings.activity_participant_exclusivity': _checked('meetings-participant-exclusivity'),
        'meetings.allow_guest_join':             _checked('meetings-allow-guest-join'),
        'meetings.access_token_expire_minutes':  parseInt(_val('meetings-session-expire'), 10),
    };
    const pwInput   = document.getElementById('meetings-password-input');
    const pwWrapper = document.getElementById('meetings-password-replace-wrapper');
    if (pwInput && pwWrapper && !pwWrapper.hidden) {
        payload['meetings.default_user_password'] = pwInput.value;
    }
    await _saveSection('meetings-feedback', payload);
};

// ══════════════════════════════════════════════════════════════════════════════
// BRAINSTORMING TAB
// ══════════════════════════════════════════════════════════════════════════════

function _renderBrainstormingTab() {
    const b        = _settings.brainstorming;
    const overrides = _settings.db_overrides || {};

    _setField('bs-char-limit',  b.idea_character_limit);
    _setField('bs-max-ideas',   b.max_ideas_per_user);
    _setField('bs-anonymity',   b.default_maintain_anonymity);
    _setField('bs-subcomments', b.default_allow_subcomments);
    _setField('bs-auto-jump',   b.default_auto_jump_new_ideas);

    [
        { dot: 'bs-char-limit',  key: 'brainstorming.idea_character_limit'        },
        { dot: 'bs-max-ideas',   key: 'brainstorming.max_ideas_per_user'          },
        { dot: 'bs-anonymity',   key: 'brainstorming.default_maintain_anonymity'  },
        { dot: 'bs-subcomments', key: 'brainstorming.default_allow_subcomments'   },
        { dot: 'bs-auto-jump',   key: 'brainstorming.default_auto_jump_new_ideas' },
    ].forEach(({ dot, key }) => _setOverrideDot(`[data-dot="${dot}"]`, Boolean(overrides[key])));

    _watchDirty('bs-char-limit', 'bs-max-ideas');
    _watchDirtyCheckbox('bs-anonymity', 'bs-subcomments', 'bs-auto-jump');
}

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

// ══════════════════════════════════════════════════════════════════════════════
// SECURITY TAB
// ══════════════════════════════════════════════════════════════════════════════

function _renderSecurityTab() {
    const s        = _settings.security;
    const overrides = _settings.db_overrides || {};

    _setField('sec-rate-limit-enabled',  s.login_rate_limit_enabled);
    _setField('sec-rate-limit-window',   s.login_rate_limit_window_seconds);
    _setField('sec-rate-limit-max-user', s.login_rate_limit_max_failures_per_username);
    _setField('sec-rate-limit-max-ip',   s.login_rate_limit_max_failures_per_ip);
    _setField('sec-rate-limit-lockout',  s.login_rate_limit_lockout_seconds);

    [
        { dot: 'sec-rate-limit-enabled',  key: 'security.login_rate_limit_enabled'                   },
        { dot: 'sec-rate-limit-window',   key: 'security.login_rate_limit_window_seconds'            },
        { dot: 'sec-rate-limit-max-user', key: 'security.login_rate_limit_max_failures_per_username' },
        { dot: 'sec-rate-limit-max-ip',   key: 'security.login_rate_limit_max_failures_per_ip'       },
        { dot: 'sec-rate-limit-lockout',  key: 'security.login_rate_limit_lockout_seconds'           },
    ].forEach(({ dot, key }) => _setOverrideDot(`[data-dot="${dot}"]`, Boolean(overrides[key])));

    _toggleRateLimitSubfields(s.login_rate_limit_enabled);

    const masterToggle = document.getElementById('sec-rate-limit-enabled');
    if (masterToggle && !masterToggle.dataset.listenerAttached) {
        masterToggle.dataset.listenerAttached = '1';
        masterToggle.addEventListener('change', () => _toggleRateLimitSubfields(masterToggle.checked));
    }

    _watchDirty('sec-rate-limit-window', 'sec-rate-limit-max-user', 'sec-rate-limit-max-ip', 'sec-rate-limit-lockout');
    _watchDirtyCheckbox('sec-rate-limit-enabled');
}

function _toggleRateLimitSubfields(enabled) {
    document.querySelectorAll('.sec-rate-subfield').forEach(el => { el.disabled = !enabled; });
}

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

// ══════════════════════════════════════════════════════════════════════════════
// SECRET FIELD (password rows)
// ══════════════════════════════════════════════════════════════════════════════

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
        previewRow.hidden     = false;
        replaceWrapper.hidden = true;
        if (input) input.value = '';
    };
    const showReplace = () => {
        previewRow.hidden     = true;
        replaceWrapper.hidden = false;
        if (input) { input.value = ''; input.focus(); }
    };

    if (isSet) {
        if (previewText) previewText.textContent = preview;
        show();
    } else {
        previewRow.hidden     = true;
        replaceWrapper.hidden = false;
    }

    if (disabled) {
        if (input)      input.disabled      = true;
        if (replaceBtn) replaceBtn.disabled = true;
        if (clearBtn)   clearBtn.disabled   = true;
        return;
    }

    if (replaceBtn && !replaceBtn.dataset.listenerAttached) {
        replaceBtn.dataset.listenerAttached = '1';
        replaceBtn.addEventListener('click', showReplace);
    }
    if (clearBtn && !clearBtn.dataset.listenerAttached) {
        clearBtn.dataset.listenerAttached = '1';
        clearBtn.addEventListener('click', () => {
            if (!confirm('Remove the current value?')) return;
            if (input) input.value = '';
            previewRow.hidden     = true;
            replaceWrapper.hidden = false;
            _markDirty();
        });
    }
    if (input && !input.dataset.listenerAttached) {
        input.dataset.listenerAttached = '1';
        input.addEventListener('input', _markDirty);
    }
}

// ══════════════════════════════════════════════════════════════════════════════
// SHARED SAVE / DIRTY TRACKING
// ══════════════════════════════════════════════════════════════════════════════

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
        _setFeedback(document.getElementById(feedbackId), 'success', 'Settings saved.');
        setTimeout(() => _setFeedback(document.getElementById(feedbackId), '', ''), 4000);
    } catch (err) {
        _setFeedback(document.getElementById(feedbackId), 'error', 'Save failed: ' + err.message);
    }
}

function _watchDirty(...ids) {
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.dataset.dirtyWatcher) {
            el.dataset.dirtyWatcher = '1';
            el.addEventListener('input', _markDirty);
        }
    });
}
function _watchDirtyCheckbox(...ids) {
    ids.forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.dataset.dirtyWatcher) {
            el.dataset.dirtyWatcher = '1';
            el.addEventListener('change', _markDirty);
        }
    });
}
function _markDirty()  { _dirty = true; }
function _clearDirty() { _dirty = false; }

function _initBeforeUnload() {
    window.addEventListener('beforeunload', e => {
        if (!_dirty) return;
        e.preventDefault();
        e.returnValue = '';
    });
}

// ══════════════════════════════════════════════════════════════════════════════
// TINY HELPERS
// ══════════════════════════════════════════════════════════════════════════════

function _val(id)     { const el = document.getElementById(id); return el ? el.value : ''; }
function _checked(id) { const el = document.getElementById(id); return el ? el.checked : false; }

function _setFeedback(el, type, msg) {
    if (!el) return;
    el.textContent = msg;
    el.className   = 'settings-feedback ' + (type || '');
}

function _escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

})();
