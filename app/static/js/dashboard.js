(() => {
    const STATUS_LABELS = {
        never_started: 'Never Started',
        not_running: 'Not Running',
        running: 'Running',
        stopped: 'Stopped'
    };

    const DEFAULT_SORT = { key: 'date', direction: 'asc' };

    const state = {
        userRole: 'participant',
        roleScope: 'participant',
        capabilities: new Set(['participant']),
        loading: false,
        hideErrorTimeout: null,
        meetings: [],
        sorting: {
            meetings: { ...DEFAULT_SORT }
        }
    };

    const selectors = {
        meetingsTable: document.getElementById('meetingsTable'),
        meetingsBody: document.getElementById('meetingsBody'),
        meetingsEmpty: document.getElementById('meetingsEmpty'),
        sortControls: Array.from(document.querySelectorAll('[data-sort-role]')),
        gatedElements: Array.from(document.querySelectorAll('[data-requires-role]')),
        errorBanner: document.getElementById('dashboardError'),
        dashboardRoot: document.querySelector('.layout-container'),
        importMeetingButton: document.getElementById('importMeetingButton'),
        importMeetingFile: document.getElementById('importMeetingFile')
    };

    const refreshConfig = (() => {
        const root = selectors.dashboardRoot;
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
            intervalMs: parsePositiveInt(root?.dataset.uiRefreshDashboardIntervalSeconds, 20) * 1000,
            hiddenIntervalMs: parsePositiveInt(root?.dataset.uiRefreshHiddenIntervalSeconds, 60) * 1000,
            failureBackoffMs: parsePositiveInt(root?.dataset.uiRefreshFailureBackoffSeconds, 90) * 1000
        };
    })();

    let refreshTimer = null;
    let refreshFailures = 0;
    let refreshInFlight = false;

    const sectionConfig = {};
    if (selectors.meetingsTable && selectors.meetingsBody && selectors.meetingsEmpty) {
        sectionConfig.meetings = {
            table: selectors.meetingsTable,
            body: selectors.meetingsBody,
            empty: selectors.meetingsEmpty,
            filter: () => true
        };
    }

    const defaultEmptyMessages = {
        meetings: selectors.meetingsEmpty?.textContent ?? ''
    };

    document.addEventListener('DOMContentLoaded', () => {
        determineRoleScope();
        bindSortEvents();
        exposeGlobalActions();
        bindImportEvents();
        loadDashboardData();
        if (refreshConfig.enabled) {
            document.addEventListener('visibilitychange', () => {
                scheduleRefresh();
            });
        }
    });

    function getRefreshDelayMs() {
        if (refreshFailures > 0) {
            return refreshConfig.failureBackoffMs;
        }
        return document.hidden ? refreshConfig.hiddenIntervalMs : refreshConfig.intervalMs;
    }

    function stopRefresh() {
        if (refreshTimer) {
            clearTimeout(refreshTimer);
            refreshTimer = null;
        }
    }

    function scheduleRefresh() {
        if (!refreshConfig.enabled) {
            return;
        }
        stopRefresh();
        refreshTimer = setTimeout(() => {
            if (refreshInFlight) {
                scheduleRefresh();
                return;
            }
            refreshInFlight = true;
            loadDashboardData().finally(() => {
                refreshInFlight = false;
            });
        }, getRefreshDelayMs());
    }

    function determineRoleScope() {
        const role = (selectors.dashboardRoot?.dataset.userRole || 'participant').toLowerCase();
        state.userRole = role;
        state.capabilities = buildCapabilities(role);
        state.roleScope = role === 'participant' ? 'participant' : 'all';
        updatePanelVisibility();
    }

    function buildCapabilities(role) {
        const capabilitySet = new Set(['participant']);

        if (role === 'facilitator' || role === 'admin' || role === 'super_admin') {
            capabilitySet.add('facilitator');
        }

        if (role === 'admin' || role === 'super_admin') {
            capabilitySet.add('admin');
        }

        return capabilitySet;
    }

    function updatePanelVisibility() {
        if (!Array.isArray(selectors.gatedElements) || selectors.gatedElements.length === 0) {
            return;
        }

        selectors.gatedElements.forEach((element) => {
            const requiredValue = element.dataset.requiresRole;
            if (!requiredValue) {
                return;
            }

            const requiredRoles = parseRoles(requiredValue);
            if (requiredRoles.length === 0) {
                return;
            }

            const hasCapability = requiredRoles.some((role) => state.capabilities.has(role));
            setRoleVisibility(element, hasCapability);
        });
    }

    function parseRoles(rawRoles) {
        if (!rawRoles) {
            return [];
        }
        return rawRoles
            .split(/[,\s]+/)
            .map((role) => role.trim().toLowerCase())
            .filter(Boolean);
    }

    function setRoleVisibility(element, visible) {
        element.classList.toggle('is-role-hidden', !visible);

        if (typeof element.hidden === 'boolean') {
            element.hidden = !visible;
        } else {
            element.style.display = visible ? '' : 'none';
        }

        element.setAttribute('aria-hidden', String(!visible));
    }

    function bindSortEvents() {
        selectors.sortControls.forEach((control) => {
            control.addEventListener('click', () => {
                const section = control.dataset.sortRole;
                const key = control.dataset.sortKey;
                if (!section || !key || !sectionConfig[section]) {
                    return;
                }

                const current = state.sorting[section] || { ...DEFAULT_SORT };
                const nextDirection = current.key === key && current.direction === 'asc' ? 'desc' : 'asc';
                state.sorting[section] = { key, direction: nextDirection };

                renderMeetingTable(section, getMeetingsForSection(section));
            });
        });
    }

    function exposeGlobalActions() {
        window.navigateTo = (url) => {
            if (url) {
                window.location.href = url;
            }
        };

        window.logout = async () => {
            try {
                await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
            } catch (error) {
                console.error('Logout error:', error);
            } finally {
                localStorage.clear();
                sessionStorage.clear();
                window.location.href = '/';
            }
        };
    }

    function bindImportEvents() {
        const button = selectors.importMeetingButton;
        const input = selectors.importMeetingFile;
        if (!button || !input) {
            return;
        }

        const defaultLabel = button.textContent;

        button.addEventListener('click', () => {
            input.click();
        });

        input.addEventListener('change', async () => {
            const file = input.files && input.files[0];
            if (!file) {
                return;
            }

            button.disabled = true;
            button.textContent = 'IMPORTING...';

            try {
                const response = await fetch('/api/meetings/import', {
                    method: 'POST',
                    body: file,
                    headers: {
                        'Content-Type': 'application/zip'
                    },
                    credentials: 'include'
                });

                if (!response.ok) {
                    let message = 'Import failed. Please check the file and try again.';
                    try {
                        const payload = await response.json();
                        if (payload && payload.detail) {
                            message = payload.detail;
                        }
                    } catch (error) {
                        // ignore JSON parse errors
                    }
                    showErrorBanner(message);
                } else {
                    await loadDashboardData();
                }
            } catch (error) {
                showErrorBanner('Import failed. Please try again.');
            } finally {
                input.value = '';
                button.disabled = false;
                button.textContent = defaultLabel;
            }
        });
    }

    async function loadDashboardData() {
        setLoadingState(true);
        let success = false;

        const params = new URLSearchParams({ role: state.roleScope });

        try {
            params.set('_ts', Date.now().toString());
            const response = await fetch(`/api/meetings?${params.toString()}`, {
                credentials: 'include',
                cache: 'no-store'
            });

            if (!response.ok) {
                throw new Error(`Failed to load meetings (${response.status})`);
            }

            const payload = await response.json();
            hydrateDashboard(payload);
            success = true;
        } catch (error) {
            console.error('Dashboard load error:', error);
            showErrorBanner('We could not load your meetings right now. Please refresh or try again later.');
        } finally {
            setLoadingState(false);
            if (refreshConfig.enabled) {
                refreshFailures = success ? 0 : refreshFailures + 1;
                scheduleRefresh();
            }
        }
    }

    function hydrateDashboard(payload) {
        if (!payload || typeof payload !== 'object') {
            return;
        }

        const meetings = Array.isArray(payload.items) ? payload.items : [];
        state.meetings = meetings;

        Object.keys(sectionConfig).forEach((section) => {
            const sectionItems = getMeetingsForSection(section, meetings);
            renderMeetingTable(section, sectionItems);
        });

        updatePanelVisibility();
    }

    function getMeetingsForSection(section, source = state.meetings) {
        const config = sectionConfig[section];
        if (!config) {
            return [];
        }
        const meetings = Array.isArray(source) ? source : [];
        return meetings.filter(config.filter);
    }

    function renderMeetingTable(section, items = []) {
        const config = sectionConfig[section];
        if (!config) {
            return;
        }

        const { table, body, empty } = config;
        if (!table || !body || !empty) {
            return;
        }

        body.innerHTML = '';

        if (!items.length) {
            table.hidden = true;
            empty.hidden = false;
            updateSortIndicators(section, true);
            return;
        }

        table.hidden = false;
        empty.hidden = true;

        const sortedItems = sortMeetings(items, section);
        sortedItems.forEach((meeting) => {
            body.appendChild(buildMeetingRow(meeting));
        });

        updateSortIndicators(section);
    }

    function sortMeetings(items, section) {
        const sortSettings = state.sorting[section] || { ...DEFAULT_SORT };
        const directionModifier = sortSettings.direction === 'desc' ? -1 : 1;
        const sorted = [...items];

        sorted.sort((first, second) => {
            const comparison = compareMeetings(first, second, sortSettings.key);
            return comparison * directionModifier;
        });

        return sorted;
    }

    function compareMeetings(first, second, key) {
        switch (key) {
            case 'title':
                return compareText(first.title, second.title);
            case 'owner':
            case 'facilitator':
                return compareText(getOwnerName(first), getOwnerName(second));
            case 'date':
                return compareDate(first.start_time, second.start_time);
            case 'status':
                return compareText(
                    STATUS_LABELS[first.status] || first.status,
                    STATUS_LABELS[second.status] || second.status
                );
            default:
                return 0;
        }
    }

    function compareText(first, second) {
        const a = (first ?? '').toString();
        const b = (second ?? '').toString();
        return a.localeCompare(b, undefined, { sensitivity: 'base', numeric: true });
    }

    function getOwnerName(meeting) {
        if (!meeting || typeof meeting !== 'object') {
            return 'TBD';
        }

        const roster = Array.isArray(meeting.facilitators) ? meeting.facilitators : [];
        const owner = roster.find((facilitator) => facilitator?.is_owner);
        if (owner?.name) {
            return owner.name;
        }

        if (meeting.facilitator?.name) {
            return meeting.facilitator.name;
        }

        const namesFromList = Array.isArray(meeting.facilitator_names)
            ? meeting.facilitator_names.filter(Boolean)
            : [];

        if (namesFromList.length > 0) {
            return namesFromList[0];
        }

        const rosterNames = roster
            .map((facilitator) => facilitator?.name)
            .filter((name) => typeof name === 'string' && name.trim().length > 0);

        if (rosterNames.length > 0) {
            return rosterNames[0];
        }

        return 'TBD';
    }

    function getCoFacilitatorNames(meeting, ownerName) {
        if (!meeting || typeof meeting !== 'object') {
            return [];
        }

        const roster = Array.isArray(meeting.facilitators) ? meeting.facilitators : [];
        const coFacilitators = roster
            .filter((facilitator) => facilitator && !facilitator.is_owner)
            .map((facilitator) => facilitator?.name)
            .filter((name) => typeof name === 'string' && name.trim().length > 0);

        if (coFacilitators.length > 0) {
            return coFacilitators;
        }

        const namesFromList = Array.isArray(meeting.facilitator_names)
            ? meeting.facilitator_names.filter(Boolean)
            : [];
        const normalizedOwner = ownerName ? ownerName.trim().toLowerCase() : '';

        return namesFromList.filter((name) => {
            if (typeof name !== 'string') {
                return false;
            }
            if (!normalizedOwner) {
                return true;
            }
            return name.trim().toLowerCase() !== normalizedOwner;
        });
    }

    function compareDate(firstValue, secondValue) {
        const firstTime = normaliseTimestamp(firstValue);
        const secondTime = normaliseTimestamp(secondValue);

        if (firstTime === null && secondTime === null) {
            return 0;
        }
        if (firstTime === null) {
            return 1;
        }
        if (secondTime === null) {
            return -1;
        }
        return firstTime - secondTime;
    }

    function normaliseTimestamp(value) {
        if (!value) {
            return null;
        }
        const date = new Date(value);
        const timestamp = date.getTime();
        return Number.isNaN(timestamp) ? null : timestamp;
    }

    function buildMeetingRow(meeting) {
        const row = document.createElement('tr');
        if (meeting && typeof meeting.status === 'string') {
            row.classList.add(`status-${meeting.status}`);
        }
        if (meeting?.meeting_id) {
            row.dataset.meetingId = meeting.meeting_id;
        }

        const nameCell = document.createElement('td');
        nameCell.className = 'meeting-title-cell';

        const titleHeader = document.createElement('div');
        titleHeader.className = 'meeting-cell-header';

        const titleText = document.createElement('span');
        titleText.className = 'meeting-title';
        titleText.textContent = meeting.title || 'Untitled Meeting';
        titleHeader.appendChild(titleText);

        nameCell.appendChild(titleHeader);
        row.appendChild(nameCell);

        const facilitatorCell = document.createElement('td');
        facilitatorCell.className = 'meeting-facilitator-cell';

        const ownerName = getOwnerName(meeting);
        const ownerLine = document.createElement('div');
        ownerLine.className = 'meeting-facilitator-owner';
        ownerLine.textContent = ownerName || 'TBD';
        facilitatorCell.appendChild(ownerLine);

        const coFacilitators = getCoFacilitatorNames(meeting, ownerName);
        const ownerLabel = ownerName || 'TBD';
        if (coFacilitators.length > 0) {
            const tooltip = `Owner: ${ownerLabel}\nFacilitators: ${coFacilitators.join(', ')}`;
            facilitatorCell.title = tooltip;
            ownerLine.title = tooltip;
        } else {
            const tooltip = `Owner: ${ownerLabel}`;
            facilitatorCell.title = tooltip;
            ownerLine.title = tooltip;
        }

        row.appendChild(facilitatorCell);

        const dateCell = document.createElement('td');
        dateCell.textContent = formatDateTime(meeting.start_time);
        row.appendChild(dateCell);

        const statusCell = document.createElement('td');
        const statusPill = document.createElement('span');
        statusPill.className = `status-pill status-${meeting.status}`;
        statusPill.textContent = STATUS_LABELS[meeting.status] || meeting.status;
        statusCell.appendChild(statusPill);
        row.appendChild(statusCell);

        const actionsCell = document.createElement('td');
        actionsCell.className = 'actions-cell';

        const actionGroup = document.createElement('div');
        actionGroup.className = 'meeting-actions table-actions';

        if (canManageMeeting(meeting)) {
            actionGroup.appendChild(
                createActionButton('Settings', meeting.quick_actions?.details, 'meeting-action-btn secondary')
            );
        }
        actionGroup.appendChild(
            createActionButton('Enter Meeting', meeting.quick_actions?.enter, 'meeting-action-btn')
        );
        if (meeting.quick_actions?.view_results) {
            actionGroup.appendChild(
                createActionButton('Export Meeting', meeting.quick_actions.view_results, 'meeting-action-btn secondary')
            );
        }

        actionsCell.appendChild(actionGroup);
        row.appendChild(actionsCell);

        return row;
    }

    function canManageMeeting(meeting) {
        if (!meeting || typeof meeting !== 'object') {
            return false;
        }

        if (state.capabilities.has('admin')) {
            return true;
        }

        return meeting.is_facilitator === true;
    }

    function createActionButton(label, url, className) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.textContent = label;

        if (!url) {
            button.disabled = true;
            return button;
        }

        button.addEventListener('click', () => window.navigateTo(url));
        return button;
    }

    function updateSortIndicators(section, reset = false) {
        const controls = selectors.sortControls.filter((control) => control.dataset.sortRole === section);

        controls.forEach((control) => {
            control.classList.remove('is-active');
            control.removeAttribute('data-sort-direction');

            const header = control.closest('th');
            if (header) {
                header.setAttribute('aria-sort', 'none');
            }
        });

        if (reset) {
            return;
        }

        const sortSettings = state.sorting[section];
        if (!sortSettings) {
            return;
        }

        const activeControl = controls.find((control) => control.dataset.sortKey === sortSettings.key);
        if (!activeControl) {
            return;
        }

        activeControl.classList.add('is-active');
        activeControl.setAttribute('data-sort-direction', sortSettings.direction);

        const activeHeader = activeControl.closest('th');
        if (activeHeader) {
            const ariaValue = sortSettings.direction === 'desc' ? 'descending' : 'ascending';
            activeHeader.setAttribute('aria-sort', ariaValue);
        }
    }

    function formatDateTime(value) {
        if (!value) {
            return '—';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return '—';
        }
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        const hours = String(date.getHours()).padStart(2, '0');
        const minutes = String(date.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day} ${hours}:${minutes}`;
    }

    function setLoadingState(isLoading) {
        state.loading = isLoading;
        if (!selectors.dashboardRoot) {
            return;
        }

        selectors.dashboardRoot.classList.toggle('is-loading', isLoading);

        if (selectors.meetingsEmpty) {
            selectors.meetingsEmpty.textContent = isLoading
                ? 'Loading your meetings...'
                : defaultEmptyMessages.meetings;
        }
    }

    function showErrorBanner(message) {
        if (!selectors.errorBanner) {
            return;
        }

        selectors.errorBanner.textContent = message;
        selectors.errorBanner.hidden = false;

        if (state.hideErrorTimeout) {
            clearTimeout(state.hideErrorTimeout);
        }

        state.hideErrorTimeout = window.setTimeout(() => {
            selectors.errorBanner.hidden = true;
        }, 6000);
    }
})();
