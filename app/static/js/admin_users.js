(() => {
  const root = document.querySelector('.layout-container');
  const refreshConfig = (() => {
    const parsePositiveInt = (value, fallback) => {
      const parsed = Number.parseInt(value, 10);
      return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
    };
    const parseBool = (value, fallback) => {
      if (value === undefined || value === null || value === '') {
        return fallback;
      }
      return String(value).toLowerCase() === 'true';
    };
    return {
      enabled: parseBool(root?.dataset.uiRefreshEnabled, true),
      intervalMs: parsePositiveInt(root?.dataset.uiRefreshAdminUsersIntervalSeconds, 15) * 1000,
      hiddenIntervalMs: parsePositiveInt(root?.dataset.uiRefreshHiddenIntervalSeconds, 60) * 1000,
      failureBackoffMs: parsePositiveInt(root?.dataset.uiRefreshFailureBackoffSeconds, 90) * 1000
    };
  })();

  const state = {
    users: [],
    refreshTimer: null,
    refreshFailures: 0,
    refreshInFlight: false,
    tableInteractionActive: false
  };
  const notify = () => {};

  async function fetchUsers() {
    try {
      const url = `/api/users/?_ts=${Date.now()}`;
      const res = await fetch(url, { credentials: 'same-origin', cache: 'no-store' });
      if (!res.ok) throw new Error('Failed to fetch users');
      const data = await res.json();
      return Array.isArray(data) ? data : [];
    } catch (err) {
      console.error(err);
      notify('Failed to load users.', 'error');
      return [];
    }
  }

  function formatRoleLabel(roleValue) {
    switch (roleValue) {
      case 'super_admin':
        return 'Super Admin';
      case 'admin':
        return 'Admin';
      case 'facilitator':
        return 'Facilitator';
      case 'participant':
        return 'Participant';
      default:
        return roleValue || '';
    }
  }

  function renderRolePill(roleValue) {
    const normalized = roleValue || '';
    const label = formatRoleLabel(normalized);
    const safeClass = normalized ? normalized : 'unknown';
    return `<span class="role-pill role-pill--${safeClass}">${label}</span>`;
  }

  function normalizeAvatarColor(color) {
    const normalized = String(color || '').trim();
    return /^#[0-9a-fA-F]{6}$/.test(normalized) ? normalized : '#9CA3AF';
  }

  function normalizeAvatarPath(path) {
    const normalized = String(path || '').trim();
    if (!normalized.startsWith('/static/avatars/')) {
      return '';
    }
    return normalized;
  }

  function renderUserAvatar(user) {
    const avatarColor = normalizeAvatarColor(user.avatar_color);
    const avatarPath = normalizeAvatarPath(user.avatar_icon_path);
    if (avatarPath) {
      return `<img class="user-avatar-thumb" src="${avatarPath}" alt="" aria-hidden="true" loading="lazy" decoding="async" style="background-color: ${avatarColor};">`;
    }
    return `<span class="user-avatar-thumb user-avatar-thumb--fallback" aria-hidden="true" style="background-color: ${avatarColor};"></span>`;
  }

  function buildRoleSelect(roleValue, identifier, disabled) {
    const options = [];
    const addOption = (value) => {
      const selected = value === roleValue ? 'selected' : '';
      options.push(`<option value="${value}" ${selected}>${formatRoleLabel(value)}</option>`);
    };

    if (roleValue === 'super_admin') {
      addOption('super_admin');
    } else if (roleValue === 'admin') {
      addOption('admin');
      addOption('facilitator');
      addOption('participant');
    } else if (roleValue === 'facilitator') {
      addOption('facilitator');
      addOption('participant');
      addOption('admin');
    } else {
      addOption('participant');
      addOption('facilitator');
    }

    const disabledAttr = disabled ? 'disabled aria-disabled="true"' : '';
    return `<select data-action="set-role" data-id="${identifier}" data-current-role="${roleValue}" ${disabledAttr}>${options.join('')}</select>`;
  }

  function renderUsers(users) {
    const tbody = document.querySelector('#users-table tbody');
    if (!tbody) return;
    tbody.innerHTML = '';
    users.forEach(u => {
      const roleValue = (u.role || '').toLowerCase();
      const isSuperAdmin = roleValue === 'super_admin';
      const actionsDisabled = isSuperAdmin ? 'disabled aria-disabled="true"' : '';
      const identifier = u.login || u.email;
      const roleSelect = buildRoleSelect(roleValue, identifier, isSuperAdmin);
      const tr = document.createElement('tr');
      tr.dataset.role = roleValue;
      tr.innerHTML = `
        <td>
          <div class="user-login-cell">
            ${renderUserAvatar(u)}
            <span>${u.login || ''}</span>
          </div>
        </td>
        <td>${u.email || ''}</td>
        <td>${u.first_name || ''}</td>
        <td>${u.last_name || ''}</td>
        <td>${renderRolePill(roleValue)}</td>
        <td class="actions-cell">
          <input type="password" class="user-reset-input" placeholder="New password" ${actionsDisabled} />
          <button data-action="reset" data-id="${u.login || u.email}" ${actionsDisabled}>Reset Password</button>
          ${roleSelect}
          <button data-action="delete" data-id="${u.login || u.email}" ${actionsDisabled}>Delete</button>
        </td>
      `;
      tbody.appendChild(tr);
    });
  }

  function sortUsers(users) {
    const roleOrder = { super_admin: 0, admin: 1, facilitator: 2, participant: 3 };
    return [...users].sort((a, b) => {
      const roleA = (a.role || '').toLowerCase();
      const roleB = (b.role || '').toLowerCase();
      const orderA = roleOrder[roleA] ?? 99;
      const orderB = roleOrder[roleB] ?? 99;
      if (orderA !== orderB) return orderA - orderB;
      const loginA = (a.login || a.email || '').toLowerCase();
      const loginB = (b.login || b.email || '').toLowerCase();
      return loginA.localeCompare(loginB);
    });
  }

  async function refresh({ force = false } = {}) {
    if (!force && isInteractingWithTable()) {
      return;
    }
    const users = await fetchUsers();
    state.users = sortUsers(users);
    if (force || !isInteractingWithTable()) {
      renderUsers(applyFilter(state.users));
    }
  }

  function getFilterTerm() {
    const filterInput = document.querySelector('#filter');
    return (filterInput?.value || '').toLowerCase().trim();
  }

  function applyFilter(users) {
    const term = getFilterTerm();
    if (!term) {
      return users;
    }
    return users.filter(u =>
      (u.login || '').toLowerCase().includes(term) ||
      (u.email || '').toLowerCase().includes(term)
    );
  }

  function getRefreshDelayMs() {
    if (state.refreshFailures > 0) {
      return refreshConfig.failureBackoffMs;
    }
    return document.hidden ? refreshConfig.hiddenIntervalMs : refreshConfig.intervalMs;
  }

  function isEditingResetInput() {
    const active = document.activeElement;
    if (
      active &&
      active.closest &&
      active.closest('#users-table') &&
      ['INPUT', 'SELECT', 'BUTTON', 'TEXTAREA'].includes(active.tagName)
    ) {
      return true;
    }
    const inputs = document.querySelectorAll('.user-reset-input');
    for (const input of inputs) {
      if (input.value && input.value.trim()) {
        return true;
      }
    }
    return false;
  }

  function isInteractingWithTable() {
    return state.tableInteractionActive || isEditingResetInput();
  }

  function stopRefresh() {
    if (state.refreshTimer) {
      clearTimeout(state.refreshTimer);
      state.refreshTimer = null;
    }
  }

  function scheduleRefresh() {
    if (!refreshConfig.enabled) {
      return;
    }
    stopRefresh();
      state.refreshTimer = setTimeout(() => {
        if (state.refreshInFlight) {
          scheduleRefresh();
          return;
        }
        state.refreshInFlight = true;
        refresh()
          .then(() => {
            state.refreshFailures = 0;
          })
          .catch(() => {
            state.refreshFailures += 1;
          })
          .finally(() => {
            state.refreshInFlight = false;
            scheduleRefresh();
          });
    }, getRefreshDelayMs());
  }

  function wireActions() {
    document.addEventListener('click', async (e) => {
      const btn = e.target.closest('button');
      if (!btn) return;
      if (btn.disabled) return;
      const action = btn.dataset.action;
      const id = btn.dataset.id;
      if (action === 'delete') {
        const row = btn.closest('tr');
        const roleValue = row ? (row.dataset.role || '').toLowerCase() : '';
        if (['facilitator', 'admin', 'super_admin'].includes(roleValue)) {
          if (!confirm(`Delete ${formatRoleLabel(roleValue)} ${id}? This cannot be undone.`)) {
            return;
          }
        }
        const res = await fetch(`/api/users/${encodeURIComponent(id)}`, { method: 'DELETE', credentials: 'same-origin' });
        if (res.ok) {
          notify('User deleted.', 'success');
          refresh({ force: true });
        } else {
          notify('Failed to delete user.', 'error');
        }
      } else if (action === 'reset') {
        const row = btn.closest('tr');
        const input = row ? row.querySelector('.user-reset-input') : null;
        const newPwd = input ? input.value.trim() : '';
        if (!newPwd) {
          notify('Enter a new password first.', 'error');
          return;
        }
        const res = await fetch(`/api/users/${encodeURIComponent(id)}/reset_password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ new_password: newPwd }),
          credentials: 'same-origin'
        });
        if (res.ok) {
          if (input) input.value = '';
          notify('Password reset.', 'success');
        } else {
          notify('Failed to reset password.', 'error');
        }
      }
    });

    document.addEventListener('change', async (e) => {
      const select = e.target.closest('select[data-action="set-role"]');
      if (!select) return;
      if (select.disabled) return;
      const id = select.dataset.id;
      const newRole = select.value;
      const previousRole = select.dataset.currentRole;
      if (!id || !newRole || newRole === previousRole) return;
      const res = await fetch(`/api/users/${encodeURIComponent(id)}/role`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole }),
        credentials: 'same-origin'
      });
      if (res.ok) {
        select.dataset.currentRole = newRole;
        notify('Role updated.', 'success');
        refresh({ force: true });
      } else {
        let msg = 'Failed to update role.';
        try { const errBody = await res.json(); msg = errBody.detail || msg; } catch {}
        select.value = previousRole || select.value;
        notify(msg, 'error');
      }
    });

    const patternForm = document.querySelector('#pattern-form');
    if (patternForm) {
      patternForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(patternForm);
        const payload = {
          prefix: fd.get('prefix'),
          start: parseInt(fd.get('start'), 10),
          end: parseInt(fd.get('end'), 10),
          default_password: fd.get('default_password')
        };
        try {
          const res = await fetch('/api/users/batch/pattern', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
            credentials: 'same-origin'
          });
          if (res.ok) {
            const body = await res.json();
            const skippedCount = Array.isArray(body.skipped) ? body.skipped.length : 0;
            notify(
              `Pattern batch complete. Created ${body.created_count}, updated ${body.updated_count || 0}, skipped ${skippedCount}.`,
              'success'
            );
          } else {
            let msg = 'Pattern batch failed.';
            try { const errBody = await res.json(); msg += ` ${errBody.detail || ''}`; } catch {}
            notify(msg, 'error');
          }
          refresh({ force: true });
        } catch (err) {
          console.error(err);
          notify('Network error on pattern batch.', 'error');
        }
      });
    }

    const emailsForm = document.querySelector('#emails-form');
    if (emailsForm) {
      emailsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const fd = new FormData(emailsForm);
        const emails = (fd.get('emails') || '').split(',').map(s => s.trim()).filter(Boolean);
        const payload = { emails, default_password: fd.get('default_password') };
        try {
          const res = await fetch('/api/users/batch/emails', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), credentials: 'same-origin'
          });
          if (res.ok) {
            const body = await res.json();
            const skippedCount = Array.isArray(body.skipped) ? body.skipped.length : 0;
            notify(
              `Email batch complete. Created ${body.created_count}, updated ${body.updated_count || 0}, skipped ${skippedCount}.`,
              'success'
            );
          } else {
            let msg = 'Email batch failed.';
            try { const errBody = await res.json(); msg += ` ${errBody.detail || ''}`; } catch {}
            notify(msg, 'error');
          }
          refresh({ force: true });
        } catch (err) {
          console.error(err);
          notify('Network error on email batch.', 'error');
        }
      });
    }

    const filterInput = document.querySelector('#filter');
    if (filterInput) {
      filterInput.addEventListener('input', async (e) => {
        renderUsers(applyFilter(state.users));
      });
    }
  }

  function wireInteractionPause() {
    const table = document.querySelector('#users-table');
    if (!table) {
      return;
    }
    table.addEventListener('mouseenter', () => {
      state.tableInteractionActive = true;
    });
    table.addEventListener('mouseleave', () => {
      state.tableInteractionActive = false;
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    wireActions();
    wireInteractionPause();
    refresh();
    if (refreshConfig.enabled) {
      document.addEventListener('visibilitychange', () => {
        scheduleRefresh();
      });
      scheduleRefresh();
    }
  });
})();
