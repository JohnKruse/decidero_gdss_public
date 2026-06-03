/**
 * Shared participant directory picker.
 *
 * Two-column transfer UI (Available Users -> Selected Participants) backed by
 * /api/users/directory. Used by the standard meeting creator and the
 * orchestration-backed template start page so both attach real users by
 * user_id rather than free-text contacts.
 *
 * Markup contract: the host page must include the standard element IDs
 * (participantDirectoryList, participantDirectorySearch, selectedParticipantsList,
 * etc.). See create_meeting.html participants-tab for the canonical markup.
 *
 * Usage:
 *   const directory = window.createParticipantDirectory();
 *   directory.init();                       // wire controls + initial load
 *   directory.getSelectedIds();             // -> ['user-id', ...]
 *   directory.setSelectedParticipants(roster); // hydrate (edit/prefill)
 */
(function () {
    function createParticipantDirectory() {
        const participantDirectoryList = document.getElementById('participantDirectoryList');
        const participantDirectoryStatus = document.getElementById('participantDirectoryStatus');
        const participantDirectorySearch = document.getElementById('participantDirectorySearch');
        const participantDirectoryRefresh = document.getElementById('participantDirectoryRefresh');
        const participantDirectoryClearButton = document.getElementById('participantDirectoryClearButton');
        const participantDirectoryPrev = document.getElementById('participantDirectoryPrev');
        const participantDirectoryNext = document.getElementById('participantDirectoryNext');
        const participantDirectoryPageLabel = document.getElementById('participantDirectoryPageLabel');
        const availableSelectAllButton = document.getElementById('availableSelectAllButton');
        const selectedSelectAllButton = document.getElementById('selectedSelectAllButton');
        const moveToSelectedButton = document.getElementById('moveToSelectedButton');
        const moveToAvailableButton = document.getElementById('moveToAvailableButton');
        const selectedParticipantsList = document.getElementById('selectedParticipantsList');
        const selectedParticipantsStatus = document.getElementById('selectedParticipantsStatus');

        const selectedParticipants = new Map();
        const participantDirectoryState = {
            items: [],
            page: 1,
            pages: 1,
            total: 0,
            searchTerm: '',
            highlighted: new Set(),
            loading: false,
            debounce: null,
        };
        const selectedParticipantHighlights = new Set();
        let participantDirectoryInitialised = false;

        function setParticipantDirectoryStatus(message, variant = 'muted') {
            if (!participantDirectoryStatus) return;
            if (!message) {
                participantDirectoryStatus.textContent = '';
                participantDirectoryStatus.dataset.variant = '';
                return;
            }
            participantDirectoryStatus.textContent = message;
            participantDirectoryStatus.dataset.variant = variant;
        }

        function updateParticipantDirectoryPagination() {
            if (!participantDirectoryPageLabel) return;
            const totalPages = Math.max(1, participantDirectoryState.pages || 1);
            const currentPage = Math.min(participantDirectoryState.page, totalPages);
            participantDirectoryPageLabel.textContent = `Page ${currentPage} of ${totalPages}`;
        }

        function updateAvailableListButtons() {
            const selectableCount = participantDirectoryState.items.filter(
                (user) => !selectedParticipants.has(user.user_id),
            ).length;
            if (participantDirectoryClearButton) {
                participantDirectoryClearButton.disabled = participantDirectoryState.highlighted.size === 0;
            }
            if (availableSelectAllButton) {
                availableSelectAllButton.disabled = selectableCount === 0;
            }
            if (participantDirectoryPrev) {
                participantDirectoryPrev.disabled =
                    participantDirectoryState.loading || participantDirectoryState.page <= 1;
            }
            if (participantDirectoryNext) {
                const totalPages = participantDirectoryState.pages || 1;
                participantDirectoryNext.disabled =
                    participantDirectoryState.loading || participantDirectoryState.page >= totalPages;
            }
        }

        function updateSelectedListButtons() {
            if (selectedSelectAllButton) {
                selectedSelectAllButton.disabled = selectedParticipants.size === 0;
            }
            if (selectedParticipantsStatus) {
                selectedParticipantsStatus.textContent = selectedParticipants.size
                    ? `${selectedParticipants.size} participant${selectedParticipants.size === 1 ? '' : 's'} selected.`
                    : 'No participants selected.';
            }
        }

        function updateTransferControls() {
            if (moveToSelectedButton) {
                moveToSelectedButton.disabled = participantDirectoryState.highlighted.size === 0;
            }
            if (moveToAvailableButton) {
                moveToAvailableButton.disabled = selectedParticipantHighlights.size === 0;
            }
        }

        function getFriendlyName(user) {
            return [user.first_name, user.last_name].filter(Boolean).join(' ').trim() || user.login || user.user_id;
        }

        function getRoleLabel(user) {
            const roleLabel = (user.role || 'participant').toString();
            return roleLabel.charAt(0).toUpperCase() + roleLabel.slice(1);
        }

        function getRoleSortRank(user) {
            const role = (user?.role || 'participant').toString().toLowerCase();
            if (role === 'super_admin') return 0;
            if (role === 'admin') return 1;
            if (role === 'facilitator') return 2;
            if (role === 'participant') return 3;
            return 4;
        }

        function normaliseSortText(value) {
            return (value || '').toString().trim().toLowerCase();
        }

        function compareUsersByRoleAndName(a, b) {
            const roleDelta = getRoleSortRank(a) - getRoleSortRank(b);
            if (roleDelta !== 0) return roleDelta;

            const aLast = normaliseSortText(a?.last_name);
            const bLast = normaliseSortText(b?.last_name);
            if (aLast !== bLast) return aLast.localeCompare(bLast);

            const aFirst = normaliseSortText(a?.first_name);
            const bFirst = normaliseSortText(b?.first_name);
            if (aFirst !== bFirst) return aFirst.localeCompare(bFirst);

            const aLogin = normaliseSortText(a?.login || a?.user_id);
            const bLogin = normaliseSortText(b?.login || b?.user_id);
            return aLogin.localeCompare(bLogin);
        }

        function getUserInitials(user) {
            const safeFirst = (user.first_name || '').trim();
            const safeLast = (user.last_name || '').trim();
            const candidate = `${safeFirst.charAt(0)}${safeLast.charAt(0)}`.trim();
            if (candidate) return candidate.toUpperCase();
            const fallback = (user.login || user.email || user.user_id || '').replace(/[^A-Za-z0-9]/g, '');
            return fallback.slice(0, 2).toUpperCase() || '•';
        }

        function normalizeAvatarColor(value) {
            const normalized = String(value || '').trim();
            return /^#[0-9a-fA-F]{6}$/.test(normalized) ? normalized : '#6B7280';
        }

        function normalizeAvatarPath(value) {
            if (!value) return null;
            const normalized = String(value).trim();
            if (!normalized.startsWith('/static/avatars/fluent/icons/')) {
                return null;
            }
            return normalized;
        }

        function createParticipantAvatar(user) {
            const avatar = document.createElement('div');
            avatar.className = 'participant-directory-avatar';
            avatar.style.backgroundColor = normalizeAvatarColor(user?.avatar_color);
            const safePath = normalizeAvatarPath(user?.avatar_icon_path);
            if (safePath) {
                const img = document.createElement('img');
                img.src = safePath;
                img.alt = '';
                img.decoding = 'async';
                img.loading = 'lazy';
                avatar.appendChild(img);
            } else {
                avatar.textContent = getUserInitials(user);
            }
            avatar.setAttribute('aria-hidden', 'true');
            return avatar;
        }

        function renderParticipantDirectory() {
            if (!participantDirectoryList) return;
            participantDirectoryList.innerHTML = '';

            if (participantDirectoryState.loading) {
                const loading = document.createElement('div');
                loading.className = 'participant-directory-empty';
                loading.textContent = 'Loading directory…';
                participantDirectoryList.appendChild(loading);
                updateAvailableListButtons();
                updateParticipantDirectoryPagination();
                updateTransferControls();
                return;
            }

            if (participantDirectoryState.items.length === 0) {
                const empty = document.createElement('div');
                empty.className = 'participant-directory-empty';
                empty.textContent = participantDirectoryState.searchTerm
                    ? 'No users matched your search.'
                    : 'Start typing above to search the directory.';
                participantDirectoryList.appendChild(empty);
                updateAvailableListButtons();
                updateParticipantDirectoryPagination();
                updateTransferControls();
                return;
            }

            const sortedDirectoryItems = [...participantDirectoryState.items].sort(compareUsersByRoleAndName);
            sortedDirectoryItems.forEach((user) => {
                const row = document.createElement('div');
                row.className = 'participant-directory-row';
                row.tabIndex = 0;
                row.setAttribute('role', 'option');
                const alreadySelected = selectedParticipants.has(user.user_id);
                const highlighted = participantDirectoryState.highlighted.has(user.user_id);
                const friendlyName = getFriendlyName(user);
                const roleLabel = getRoleLabel(user);
                row.title = `${friendlyName}${user.login && friendlyName !== user.login ? ` (${user.login})` : ''} • ${roleLabel}`;

                if (alreadySelected) {
                    row.setAttribute('aria-disabled', 'true');
                    row.setAttribute('aria-selected', 'false');
                } else {
                    row.removeAttribute('aria-disabled');
                    row.setAttribute('aria-selected', highlighted ? 'true' : 'false');
                    row.classList.toggle('is-highlighted', highlighted);
                }

                const body = document.createElement('div');
                body.className = 'participant-directory-body';
                const infoLine = document.createElement('div');
                infoLine.className = 'participant-directory-line';
                const name = document.createElement('span');
                name.className = 'participant-directory-name';
                name.textContent = friendlyName;
                const role = document.createElement('span');
                role.className = 'participant-directory-role';
                role.textContent = roleLabel;

                infoLine.appendChild(name);
                infoLine.appendChild(role);
                body.appendChild(infoLine);

                const avatar = createParticipantAvatar(user);
                row.appendChild(avatar);
                row.appendChild(body);

                if (!alreadySelected) {
                    row.addEventListener('click', () => toggleAvailableHighlight(user.user_id));
                    row.addEventListener('dblclick', (event) => {
                        event.preventDefault();
                        addParticipantsFromDirectorySelection([user.user_id]);
                    });
                    row.addEventListener('keydown', (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            toggleAvailableHighlight(user.user_id);
                        }
                        if (event.key === 'Enter' && event.metaKey) {
                            addParticipantsFromDirectorySelection([user.user_id]);
                        }
                    });
                }

                participantDirectoryList.appendChild(row);
            });

            updateAvailableListButtons();
            updateParticipantDirectoryPagination();
            updateTransferControls();
        }

        function renderSelectedParticipants() {
            if (!selectedParticipantsList) return;
            selectedParticipantsList.innerHTML = '';

            if (selectedParticipants.size === 0) {
                const empty = document.createElement('div');
                empty.className = 'participant-directory-empty';
                empty.textContent = 'No participants selected yet.';
                selectedParticipantsList.appendChild(empty);
            } else {
                const sortedSelectedParticipants = Array.from(selectedParticipants.values()).sort(compareUsersByRoleAndName);
                sortedSelectedParticipants.forEach((participant) => {
                    const row = document.createElement('div');
                    row.className = 'participant-directory-row participant-directory-row--selected';
                    row.dataset.userId = participant.user_id;
                    row.tabIndex = 0;
                    row.setAttribute('role', 'option');
                    const isHighlighted = selectedParticipantHighlights.has(participant.user_id);
                    row.classList.toggle('is-highlighted', isHighlighted);
                    row.setAttribute('aria-selected', isHighlighted ? 'true' : 'false');

                    const body = document.createElement('div');
                    body.className = 'participant-directory-body';
                    const infoLine = document.createElement('div');
                    infoLine.className = 'participant-directory-line';
                    const name = document.createElement('span');
                    name.className = 'participant-directory-name';
                    const friendlyName = getFriendlyName(participant);
                    name.textContent = friendlyName;

                    const role = document.createElement('span');
                    role.className = 'participant-directory-role';
                    role.textContent = getRoleLabel(participant);

                    infoLine.appendChild(name);
                    infoLine.appendChild(role);
                    body.appendChild(infoLine);

                    const avatar = createParticipantAvatar(participant);
                    row.appendChild(avatar);
                    row.appendChild(body);

                    row.addEventListener('click', () => toggleSelectedHighlight(participant.user_id));
                    row.addEventListener('dblclick', (event) => {
                        event.preventDefault();
                        removeParticipantsFromSelection([participant.user_id]);
                    });
                    row.addEventListener('keydown', (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            toggleSelectedHighlight(participant.user_id);
                        }
                    });

                    selectedParticipantsList.appendChild(row);
                });
            }

            updateSelectedListButtons();
            updateTransferControls();
        }

        function toggleAvailableHighlight(userId) {
            if (participantDirectoryState.highlighted.has(userId)) {
                participantDirectoryState.highlighted.delete(userId);
            } else {
                participantDirectoryState.highlighted.add(userId);
            }
            renderParticipantDirectory();
        }

        function toggleSelectedHighlight(userId) {
            if (selectedParticipantHighlights.has(userId)) {
                selectedParticipantHighlights.delete(userId);
            } else {
                selectedParticipantHighlights.add(userId);
            }
            renderSelectedParticipants();
        }

        function selectAllAvailable() {
            const selectable = participantDirectoryState.items
                .filter((user) => !selectedParticipants.has(user.user_id))
                .map((user) => user.user_id);
            participantDirectoryState.highlighted = new Set(selectable);
            renderParticipantDirectory();
        }

        function selectAllSelected() {
            selectedParticipantHighlights.clear();
            selectedParticipants.forEach((_, userId) => selectedParticipantHighlights.add(userId));
            renderSelectedParticipants();
        }

        async function loadParticipantDirectory({ resetPage = false } = {}) {
            if (!participantDirectoryList) {
                return;
            }
            if (resetPage) {
                participantDirectoryState.page = 1;
            }
            participantDirectoryState.loading = true;
            setParticipantDirectoryStatus('Loading directory…', 'info');
            renderParticipantDirectory();
            try {
                const params = new URLSearchParams({
                    draft: 'true',
                    page: String(participantDirectoryState.page),
                    page_size: '25',
                    sort: 'name',
                });
                if (participantDirectoryState.searchTerm) {
                    params.set('q', participantDirectoryState.searchTerm);
                }
                const response = await fetch(`/api/users/directory?${params.toString()}`, { credentials: 'include' });
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    throw new Error(err?.detail || 'Unable to load directory.');
                }
                const payload = await response.json();
                participantDirectoryState.items = Array.isArray(payload?.items) ? payload.items : [];
                participantDirectoryState.pages = payload?.pagination?.pages || 1;
                participantDirectoryState.total = payload?.pagination?.total || participantDirectoryState.items.length;
                participantDirectoryState.highlighted.clear();
                setParticipantDirectoryStatus(
                    participantDirectoryState.items.length === 0
                        ? 'No users matched your search.'
                        : 'Select users and use the arrow to add them.',
                    participantDirectoryState.items.length === 0 ? 'muted' : 'success',
                );
            } catch (error) {
                console.error('Directory load failed:', error);
                participantDirectoryState.items = [];
                setParticipantDirectoryStatus(error.message || 'Unable to load directory.', 'error');
            } finally {
                participantDirectoryState.loading = false;
                renderParticipantDirectory();
            }
        }

        function handleParticipantDirectorySearchInput(term) {
            participantDirectoryState.searchTerm = (term || '').trim();
            if (participantDirectoryState.debounce) {
                clearTimeout(participantDirectoryState.debounce);
            }
            participantDirectoryState.debounce = setTimeout(() => {
                participantDirectoryState.highlighted.clear();
                loadParticipantDirectory({ resetPage: true });
            }, 300);
        }

        function changeParticipantDirectoryPage(delta) {
            const next = participantDirectoryState.page + delta;
            if (next < 1) return;
            const totalPages = participantDirectoryState.pages || 1;
            if (next > totalPages) return;
            participantDirectoryState.page = next;
            loadParticipantDirectory();
        }

        function clearParticipantDirectorySelection() {
            participantDirectoryState.highlighted.clear();
            renderParticipantDirectory();
            setParticipantDirectoryStatus('Selection cleared.', 'muted');
        }

        function addParticipantsFromDirectorySelection(userIds = null) {
            const ids = Array.isArray(userIds) && userIds.length > 0
                ? userIds
                : Array.from(participantDirectoryState.highlighted);
            if (ids.length === 0) return;

            ids.forEach((userId) => {
                const entry =
                    participantDirectoryState.items.find((item) => item.user_id === userId) ||
                    selectedParticipants.get(userId);
                if (entry) {
                    selectedParticipants.set(userId, entry);
                }
            });
            participantDirectoryState.highlighted.clear();
            selectedParticipantHighlights.clear();
            renderSelectedParticipants();
            renderParticipantDirectory();
            setParticipantDirectoryStatus('Participants added.', 'success');
        }

        function removeParticipantsFromSelection(userIds = null) {
            const ids = Array.isArray(userIds) && userIds.length > 0
                ? userIds
                : Array.from(selectedParticipantHighlights);
            if (ids.length === 0) return;
            ids.forEach((userId) => selectedParticipants.delete(userId));
            selectedParticipantHighlights.clear();
            renderSelectedParticipants();
            renderParticipantDirectory();
            setParticipantDirectoryStatus('Participants removed.', 'muted');
        }

        function setupParticipantDirectoryControls() {
            if (participantDirectorySearch) {
                participantDirectorySearch.addEventListener('input', (event) =>
                    handleParticipantDirectorySearchInput(event.target.value || ''),
                );
            }
            if (participantDirectoryRefresh) {
                participantDirectoryRefresh.addEventListener('click', () => {
                    participantDirectoryState.searchTerm = '';
                    if (participantDirectorySearch) {
                        participantDirectorySearch.value = '';
                    }
                    loadParticipantDirectory({ resetPage: true });
                });
            }
            if (participantDirectoryClearButton) {
                participantDirectoryClearButton.addEventListener('click', clearParticipantDirectorySelection);
            }
            if (availableSelectAllButton) {
                availableSelectAllButton.addEventListener('click', selectAllAvailable);
            }
            if (selectedSelectAllButton) {
                selectedSelectAllButton.addEventListener('click', selectAllSelected);
            }
            if (moveToSelectedButton) {
                moveToSelectedButton.addEventListener('click', () => addParticipantsFromDirectorySelection());
            }
            if (moveToAvailableButton) {
                moveToAvailableButton.addEventListener('click', () => removeParticipantsFromSelection());
            }
            if (participantDirectoryPrev) {
                participantDirectoryPrev.addEventListener('click', () => changeParticipantDirectoryPage(-1));
            }
            if (participantDirectoryNext) {
                participantDirectoryNext.addEventListener('click', () => changeParticipantDirectoryPage(1));
            }
        }

        function initialiseParticipantDirectory() {
            if (participantDirectoryInitialised) return;
            participantDirectoryInitialised = true;
            renderSelectedParticipants();
            loadParticipantDirectory({ resetPage: true });
        }

        // ---- Public API -------------------------------------------------

        /** Wire up controls and trigger the first directory load. Idempotent. */
        function init() {
            if (participantDirectoryInitialised) return;
            setupParticipantDirectoryControls();
            initialiseParticipantDirectory();
        }

        /** Return the currently selected participant user IDs. */
        function getSelectedIds() {
            return Array.from(selectedParticipants.keys());
        }

        /**
         * Replace the selected set from a roster of user-like entries.
         * Accepts directory items, meeting participants, or {user_id} stubs.
         */
        function setSelectedParticipants(roster) {
            selectedParticipants.clear();
            (Array.isArray(roster) ? roster : []).forEach((entry) => {
                const userId = entry.user_id || entry.id || entry.login;
                if (!userId) return;
                selectedParticipants.set(userId, {
                    user_id: userId,
                    first_name: entry.first_name || '',
                    last_name: entry.last_name || '',
                    login: entry.login || entry.email || userId,
                    email: entry.email || '',
                    role: entry.role || 'participant',
                    avatar_color: entry.avatar_color,
                    avatar_icon_path: entry.avatar_icon_path,
                });
            });
            renderSelectedParticipants();
            renderParticipantDirectory();
        }

        return {
            init,
            getSelectedIds,
            setSelectedParticipants,
            renderSelectedParticipants,
        };
    }

    window.createParticipantDirectory = createParticipantDirectory;
})();
