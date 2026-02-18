(() => {
    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector("[data-meeting-root]");
        if (!root) {
            return;
        }
        const realtimeAvailable = Boolean(window.DecideroRealtime);

        const meetingId = root.dataset.meetingId;
        if (!meetingId) {
            console.warn("Meeting page missing meetingId context.");
            return;
        }

        const context = {
            meetingId,
            userLogin: root.dataset.userLogin || null,
            userId: root.dataset.userId || null,
            userRole: (root.dataset.userRole || "participant").toLowerCase(),
        };
        const isAdminUser = context.userRole === "admin" || context.userRole === "super_admin";
        const brainstormingLimits = {
            ideaCharacterLimit: Number(root.dataset.brainstormMaxLength || "") || 500,
            maxIdeasPerUser: Number(root.dataset.brainstormMaxIdeas || "") || 0,
        };
        const meetingRefreshConfig = (() => {
            const parsePositiveInt = (value, fallback) => {
                const parsed = Number.parseInt(value, 10);
                return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
            };
            const parseBool = (value, fallback) => {
                if (value === undefined || value === null || value === "") {
                    return fallback;
                }
                return String(value).toLowerCase() === "true";
            };

            const enabled = parseBool(root.dataset.meetingRefreshEnabled, true);
            const intervalSeconds = parsePositiveInt(root.dataset.meetingRefreshIntervalSeconds, 8);
            const hiddenIntervalSeconds = parsePositiveInt(
                root.dataset.meetingRefreshHiddenIntervalSeconds,
                45,
            );
            const failureBackoffSeconds = parsePositiveInt(
                root.dataset.meetingRefreshFailureBackoffSeconds,
                60,
            );
            return {
                enabled,
                intervalMs: intervalSeconds * 1000,
                hiddenIntervalMs: hiddenIntervalSeconds * 1000,
                failureBackoffMs: failureBackoffSeconds * 1000,
            };
        })();

        const DEFAULT_MODULES = [
            {
                tool_type: "brainstorming",
                label: "Brainstorming",
                description: "Capture ideas collaboratively and surface them to the group in real time.",
                default_config: {
                    allow_anonymous: false,
                    allow_subcomments: false,
                    auto_jump_new_ideas: true,
                    prompt: "",
                },
                reliability_policy: {
                    write_default: {
                        retryable_statuses: [429, 502, 503, 504],
                        max_retries: 2,
                        base_delay_ms: 350,
                        max_delay_ms: 1800,
                        jitter_ratio: 0.2,
                        idempotency_header: "X-Idempotency-Key",
                    },
                    submit_idea: {
                        retryable_statuses: [429, 502, 503, 504],
                        max_retries: 3,
                        base_delay_ms: 400,
                        max_delay_ms: 2500,
                        jitter_ratio: 0.25,
                        idempotency_header: "X-Idempotency-Key",
                    },
                },
            },
            {
                tool_type: "voting",
                label: "Dot Voting",
                description: "Distribute votes across ideas to prioritise the strongest options.",
                default_config: {
                    vote_type: "dot",
                    max_votes: 5,
                    max_votes_per_option: 5,
                    allow_retract: true,
                    show_results_immediately: false,
                    randomize_participant_order: false,
                    options: ["Edit vote option here"],
                },
                reliability_policy: {
                    write_default: {
                        retryable_statuses: [429, 502, 503, 504],
                        max_retries: 2,
                        base_delay_ms: 350,
                        max_delay_ms: 1800,
                        jitter_ratio: 0.2,
                        idempotency_header: "X-Idempotency-Key",
                    },
                    cast_vote: {
                        retryable_statuses: [429, 502, 503, 504],
                        max_retries: 2,
                        base_delay_ms: 300,
                        max_delay_ms: 1500,
                        jitter_ratio: 0.2,
                        idempotency_header: "X-Idempotency-Key",
                    },
                },
            },
            {
                tool_type: "categorization",
                label: "Bucketing - Facilitator",
                description: "Sort ideas into facilitator-defined buckets.",
                default_config: {
                    mode: "FACILITATOR_LIVE",
                    items: [],
                    buckets: [],
                    single_assignment_only: true,
                },
                reliability_policy: {
                    write_default: {
                        retryable_statuses: [429, 502, 503, 504],
                        max_retries: 2,
                        base_delay_ms: 350,
                        max_delay_ms: 1800,
                        jitter_ratio: 0.2,
                        idempotency_header: "X-Idempotency-Key",
                    },
                },
            },
        ];

        const CONFIG_LABEL_MAP = {
            allow_anonymous: "Maintain Anonymity",
            allow_subcomments: "Allow Subcomments",
            auto_jump_new_ideas: "Auto-jump to newest idea",
            max_votes: "Total dots per participant",
            max_votes_per_option: "Dots per idea (1-9)",
            show_results_immediately: "Show results to participants before submission",
            options: "Vote candidates",
            randomize_participant_order: "Randomize participant idea order",
            mode: "Categorization mode",
            items: "Ideas to categorize",
            buckets: "Buckets",
            single_assignment_only: "Single assignment only",
        };

        const ui = {
            statusBadge: document.getElementById("meetingConnectionStatus"),
            participantsList: document.getElementById("meetingParticipants"),
            eventsLog: document.getElementById("meetingEventsLog"),
            state: {
                status: document.getElementById("meetingStateStatus"),
                activity: document.getElementById("meetingStateActivity"),
                tool: document.getElementById("meetingStateTool"),
                updated: document.getElementById("meetingStateUpdated"),
                metadata: document.getElementById("meetingStateMetadata"),
            },
            agendaList: document.getElementById("meetingAgendaList"),
            agendaCard: document.querySelector(".meeting-agenda-card"),
            agendaCollapseToggle: document.getElementById("agendaCollapseToggle"),
            agendaSectionBody: document.getElementById("agendaSectionBody"),
            agendaSummaryTotal: document.getElementById("agendaSummaryTotal"),
            agendaSummaryActive: document.getElementById("agendaSummaryActive"),
            accessNotice: document.getElementById("meetingAccessMessage"),
            meetingOverview: {
                title: document.getElementById("meetingOverviewTitle"),
                description: document.getElementById("meetingOverviewDescription"),
                statusTitle: document.getElementById("meetingOverviewStatusTitle"),
                statusBadge: document.getElementById("meetingOverviewStatusBadge"),
                facilitator: document.getElementById("meetingOverviewFacilitator"),
            },
            activityDetails: {
                container: document.getElementById("meetingActivityDetails"),
                title: document.getElementById("activityDetailsTitle"),
                status: document.getElementById("activityDetailsStatus"),
                tool: document.getElementById("activityDetailsTool"),
                instructions: document.getElementById("activityDetailsInstructions"),
                configSection: document.getElementById("activityDetailsConfigSection"),
                configList: document.getElementById("activityDetailsConfig"),
            },
            facilitatorControls: {
                // Main controls moved to agenda items
                // Removed: start, pause, resume, stop, elapsedTimeDisplay, prev, next

                feedback: document.getElementById("facilitatorControlFeedback"), // May need relocation or removal if feedback is per-item
                participantAdmin: document.querySelector("[data-participant-admin]"),
                participantForm: document.getElementById("participantAssignForm"),
                participantInput: document.getElementById("participantAssignLogin"),
                meetingDirectoryList: document.getElementById("meetingDirectoryList"),
                meetingDirectoryStatus: document.getElementById("meetingDirectoryStatus"),
                meetingDirectorySearch: document.getElementById("meetingDirectorySearch"),
                meetingDirectoryClearButton: document.getElementById("meetingDirectoryClearButton"),
                meetingDirectoryPrev: document.getElementById("meetingDirectoryPrev"),
                meetingDirectoryNext: document.getElementById("meetingDirectoryNext"),
                meetingDirectoryPageLabel: document.getElementById("meetingDirectoryPageLabel"),
                meetingAvailableSelectAll: document.getElementById("meetingAvailableSelectAllButton"),
                meetingSelectedSelectAll: document.getElementById("meetingSelectedSelectAllButton"),
                meetingMoveToSelected: document.getElementById("meetingMoveToSelectedButton"),
                meetingMoveToAvailable: document.getElementById("meetingMoveToAvailableButton"),
                meetingSelectedList: document.getElementById("meetingSelectedList"),
                meetingSelectedStatus: document.getElementById("meetingSelectedStatus"),
                participantFeedback: document.getElementById("participantAdminFeedback"),
                activityAdmin: document.querySelector("[data-activity-participant-admin]"),
                activityList: document.getElementById("activityParticipantChecklist"),
                activitySelectedList: document.getElementById("activityParticipantSelectedList"),
                activityAvailableSelectAll: document.getElementById("activityAvailableSelectAllButton"),
                activitySelectedSelectAll: document.getElementById("activitySelectedSelectAllButton"),
                activityMoveToSelected: document.getElementById("activityMoveToSelectedButton"),
                activityMoveToAvailable: document.getElementById("activityMoveToAvailableButton"),
                activityIncludeAll: document.getElementById("activityParticipantIncludeAll"),
                activityReuse: document.getElementById("activityParticipantReuse"),
                activityApply: document.getElementById("activityParticipantApply"),
                activityFeedback: document.getElementById("activityParticipantFeedback"),

                // New agenda activity controls
                addActivityButton: document.getElementById("agendaAddActivityButton"),
                addActivityModal: document.getElementById("addActivityModal"),
                closeAddActivityModal: document.getElementById("closeAddActivityModal"),
                cancelAddActivity: document.getElementById("cancelAddActivity"),
                addActivityForm: document.getElementById("addActivityForm"),
                newActivityTitle: document.getElementById("newActivityTitle"),
                newActivityToolType: document.getElementById("newActivityToolType"),
                newActivityInstructions: document.getElementById("newActivityInstructions"),
                newActivityOrderIndex: document.getElementById("newActivityOrderIndex"),
            },
            // Modals
            participantAdminModal: document.getElementById("participantAdminModal"),
            participantModalTitle: document.getElementById("participantModalTitle"),
            participantModalActivityMeta: document.getElementById("participantModalActivityMeta"),
            participantModalActivityName: document.getElementById("participantModalActivityName"),
            participantModalActivityType: document.getElementById("participantModalActivityType"),
            participantModalTabs: Array.from(document.querySelectorAll("[data-participant-modal-tab]")),
            participantAdminPanel: document.querySelector("[data-participant-admin-panel]"),
            activityRosterPanel: document.querySelector("[data-activity-roster-panel]"),
            closeParticipantAdminModal: document.getElementById("closeParticipantAdminModal"),
            openParticipantAdminButton: document.getElementById("openParticipantAdminButton"),

            genericPanel: {
                root: document.querySelector("[data-generic-tool]"),
                title: document.getElementById("genericToolTitle"),
                description: document.getElementById("genericToolDescription"),
            },
            // Collision Modal
            collisionModal: document.getElementById("collisionModal"),
            closeCollisionModal: document.getElementById("closeCollisionModal"),
            cancelCollision: document.getElementById("cancelCollision"),
            conflictingParticipantsList: document.getElementById("conflictingParticipantsList"),
        };

        const brainstorming = {
            root: document.querySelector("[data-brainstorming-root]"),
            title: document.getElementById("brainstormingHeaderTitle"),
            description: document.getElementById("brainstormingDescription"),
            form: document.querySelector("[data-brainstorming-form]"),
            textarea: document.getElementById("brainstormingIdeaInput"),
            submit: document.getElementById("brainstormingSubmitButton"),
            ideasList: document.getElementById("brainstormingIdeasList"),
            ideasBody: document.getElementById("brainstormingIdeasBody"),
            autoJumpToggle: document.getElementById("brainstormingAutoJumpToggle"),
            error: document.getElementById("brainstormingError"),
        };

        const voting = {
            root: document.querySelector("[data-voting-root]"),
            list: document.getElementById("votingOptionsList"),
            instructions: document.getElementById("votingInstructions"),
            remaining: document.getElementById("votingRemaining"),
            notice: document.getElementById("votingResultsNotice"),
            error: document.getElementById("votingError"),
            footer: document.getElementById("votingFooter"),
            progress: document.getElementById("votingProgressMessage"),
            submit: document.getElementById("votingSubmitButton"),
            reset: document.getElementById("votingResetButton"),
            status: document.getElementById("votingStatus"),
            viewResultsButton: document.getElementById("votingViewResultsButton"),
            resultsModal: document.getElementById("votingResultsModal"),
            resultsTable: document.getElementById("votingResultsTable"),
            resultsBody: document.getElementById("votingResultsBody"),
            closeResultsModal: document.getElementById("closeVotingResultsModal"),
            timingDebug: document.getElementById("votingTimingDebug"),
        };

        const categorization = {
            root: document.querySelector("[data-categorization-root]"),
            instructions: document.getElementById("categorizationInstructions"),
            error: document.getElementById("categorizationError"),
            openBucketTitle: document.getElementById("categorizationOpenBucketTitle"),
            itemsList: document.getElementById("categorizationItemsList"),
            addItem: document.getElementById("categorizationAddItemButton"),
            editItem: document.getElementById("categorizationEditItemButton"),
            deleteItem: document.getElementById("categorizationDeleteItemButton"),
            bucketsList: document.getElementById("categorizationBucketsList"),
            refresh: document.getElementById("categorizationRefreshButton"),
            addBucket: document.getElementById("categorizationAddBucketButton"),
            editBucket: document.getElementById("categorizationEditBucketButton"),
            deleteBucket: document.getElementById("categorizationDeleteBucketButton"),
        };

        const transfer = {
            root: document.querySelector("[data-transfer-root]"),
            close: document.getElementById("closeTransferPanel"),
            status: document.getElementById("transferStatus"),
            error: document.getElementById("transferError"),
            donorTitle: document.getElementById("transferDonorTitle"),
            includeComments: document.getElementById("transferIncludeComments"),
            targetToolType: document.getElementById("transferTargetToolType"),
            transformProfile: document.getElementById("transferTransformProfile"),
            addIdea: document.getElementById("transferAddIdea"),
            ideasList: document.getElementById("transferIdeasList"),
            ideasBody: document.getElementById("transferIdeasBody"),
            saveDraft: document.getElementById("saveTransferDraft"),
            commit: document.getElementById("commitTransfer"),
        };

        const participants = new Map();
        const assignedParticipants = new Map();
        const meetingDirectoryState = {
            items: [],
            page: 1,
            pages: 1,
            total: 0,
            searchTerm: "",
            loading: false,
            highlighted: new Set(),
            debounce: null,
        };
        const meetingSelectedHighlights = new Set();
        let participantDirectoryInitialized = false;

        const state = {
            moduleCatalog: [...DEFAULT_MODULES],
            moduleMap: new Map(DEFAULT_MODULES.map((entry) => [entry.tool_type.toLowerCase(), entry])),
            meeting: null,
            agenda: [],
            agendaMap: new Map(),
            selectedActivityId: null,
            activeActivityId: null,
            activeActivities: {},
            selectionMode: "auto",
            latestState: null,
            isFacilitator: false,
            isParticipant: false,
            facilitatorBusy: false,
            activityAssignments: new Map(),
            participantStage: "waiting",
            participantRestricted: false,
            requestedActivityId: null,

            // Timer related state
            timerInterval: null,
            elapsedTime: 0, // in seconds
            timerStartTime: null, // Unix timestamp (ms) when timer started/resumed
            timerPausedTime: null, // Unix timestamp (ms) when timer paused
        };

        function startTimer() {
            // Lightweight local timer for UI badges; falls back to server timestamps for accuracy.
            stopTimer();
            state.timerStartTime = Date.now();
            state.timerInterval = setInterval(() => {
                if (state.timerStartTime) {
                    const now = Date.now();
                    const base = state.timerPausedTime || 0;
                    state.elapsedTime = base + Math.max(0, Math.floor((now - state.timerStartTime) / 1000));
                }
            }, 1000);
        }

        function pauseTimer() {
            if (state.timerInterval) {
                clearInterval(state.timerInterval);
                state.timerInterval = null;
            }
            if (state.timerStartTime) {
                const now = Date.now();
                state.timerPausedTime =
                    (state.timerPausedTime || 0) + Math.max(0, Math.floor((now - state.timerStartTime) / 1000));
                state.timerStartTime = null;
            }
        }

        function stopTimer() {
            if (state.timerInterval) {
                clearInterval(state.timerInterval);
                state.timerInterval = null;
            }
            state.timerStartTime = null;
            state.timerPausedTime = 0;
            state.elapsedTime = 0;
        }

        function getActiveActivities(excludeActivityId = null) {
            const active = [];
            Object.values(state.activeActivities || {}).forEach((entry) => {
                if (!entry || typeof entry !== "object") return;
                const id = entry.activityId || entry.activity_id;
                const status = (entry.status || "").toLowerCase();
                if (!id || status === "completed" || status === "stopped") return;
                if (excludeActivityId && id === excludeActivityId) return;
                active.push({ id, status });
            });

            const currentId = state.latestState?.currentActivity;
            const currentStatus = (state.latestState?.status || "").toLowerCase();
            if (
                currentId &&
                (!excludeActivityId || currentId !== excludeActivityId) &&
                currentStatus &&
                currentStatus !== "completed" &&
                currentStatus !== "stopped" &&
                !active.some((entry) => entry.id === currentId)
            ) {
                active.push({ id: currentId, status: currentStatus });
            }
            return active;
        }

        function getActivityRosterSummary(activityId) {
            if (!activityId) return null;
            const assignment = state.activityAssignments.get(activityId);
            const activeEntry = state.activeActivities?.[activityId];
            const meta =
                activeEntry?.metadata ||
                (state.latestState?.currentActivity === activityId ? state.latestState?.metadata : null);
            const metaScope = (meta?.participantScope || meta?.participant_scope || "").toLowerCase();
            const metaIds = Array.isArray(meta?.participantIds || meta?.participant_ids)
                ? meta.participantIds || meta.participant_ids
                : [];

            let mode = assignment?.mode || "all";
            let selectedIds = assignment?.participant_ids || [];
            if (metaScope === "custom") {
                mode = "custom";
                selectedIds = metaIds;
            } else if (metaScope === "all") {
                mode = "all";
                selectedIds = [];
            }

            const liveList = Array.isArray(activeEntry?.participantIds)
                ? activeEntry.participantIds
                : [];

            const total =
                mode === "custom"
                    ? selectedIds.length
                    : assignment?.available_participants?.length ||
                    liveList.length ||
                    (state.meeting?.participant_ids || []).length ||
                    0;

            return {
                text:
                    mode === "custom"
                        ? `Custom • ${total} selected`
                        : `All participants${total ? ` • ${total}` : ""}`,
                isLive: Boolean(activeEntry),
            };
        }

        function normalizeIdList(ids) {
            if (!Array.isArray(ids)) return [];
            return ids.map((id) => String(id)).filter(Boolean);
        }

        function getMeetingParticipantIds() {
            return normalizeIdList(state.meeting?.participant_ids || []);
        }

        function getActivityParticipantIds(item, activityState) {
            const liveIds = normalizeIdList(activityState?.participantIds || activityState?.participant_ids);
            if (liveIds.length) return liveIds;
            const configIds = normalizeIdList(item?.config?.participant_ids);
            if (configIds.length) return configIds;
            return getMeetingParticipantIds();
        }

        function getActiveParticipantCount(item, activityState) {
            if (!activityState) return null;
            const active = normalizeIdList(state.latestState?.participants || []);
            if (active.length === 0) return 0;
            const allowed = new Set(getActivityParticipantIds(item, activityState));
            const meetingParticipants = new Set(getMeetingParticipantIds());
            let count = 0;
            active.forEach((id) => {
                if (allowed.size && !allowed.has(id)) return;
                if (meetingParticipants.size && !meetingParticipants.has(id)) return;
                count += 1;
            });
            return count;
        }

        function getActivityAccessState(item, activityState, isActive) {
            if (state.isFacilitator) {
                return {
                    isOpen: Boolean(isActive),
                    canEnter: true,
                    title: isActive ? "Open to participants now" : "Not running yet",
                };
            }
            const userId = context.userId ? String(context.userId) : "";
            const allowed = new Set(getActivityParticipantIds(item, activityState));
            const isEligible = !userId || allowed.size === 0 || allowed.has(userId);
            if (!isActive) {
                return { isOpen: false, canEnter: false, title: "Not running yet" };
            }
            if (!isEligible) {
                return { isOpen: false, canEnter: false, title: "Not assigned to you" };
            }
            return { isOpen: true, canEnter: true, title: "Open to you now" };
        }

        let meetingSocket = null;
        let heartbeatTimer = null;
        let brainstormingActive = false;
        let brainstormingActivityId = null;
        let brainstormingIdeasLoaded = false;
        let brainstormingSubmitInFlight = false;
        const writeReliabilityDefaults = {
            retryableStatuses: [429, 502, 503, 504],
            maxRetries: 2,
            baseDelayMs: 350,
            maxDelayMs: 1800,
            jitterRatio: 0.2,
            idempotencyHeader: "X-Idempotency-Key",
        };
        const reliableActionQueues = new Map();
        const brainstormingIdeaIds = new Set();
        const brainstormingIdeaNumbers = new Map();
        const brainstormingSubcommentCounts = new Map();
        let brainstormingIdeaCount = 0;
        let meetingRefreshTimer = null;
        let meetingRefreshInFlight = false;
        let meetingRefreshFailures = 0;
        let realtimeConnected = false;
        let activeBrainstormingConfig = {};
        let votingSummary = null;
        let votingActivityId = null;
        let votingRequestInFlight = false;
        let votingOptionsRefreshInFlight = false;
        let votingIsActive = false;
        let votingDraftActivityId = null;
        let votingDraftDirty = false;
        let votingDraftSignature = null;
        let votingDraftVotes = new Map();
        let votingCommittedVotes = new Map();
        let activeVotingConfig = {};
        const votingTiming = (() => {
            const params = new URLSearchParams(window.location.search || "");
            const enabledFromQuery = params.get("votingTiming") === "1";
            const enabledFromStorage = localStorage.getItem("decidero:voting-timing") === "1";
            const enabled = Boolean(enabledFromQuery || enabledFromStorage);
            const maxEvents = 120;
            const events = [];
            let session = null;
            let latestState = null;

            function nowMs() {
                return window.performance && typeof window.performance.now === "function"
                    ? window.performance.now()
                    : Date.now();
            }

            function trimEvents() {
                if (events.length > maxEvents) {
                    events.splice(0, events.length - maxEvents);
                }
            }

            function notifyUpdate() {
                if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
                    window.dispatchEvent(new CustomEvent("decidero:voting-timing-update"));
                }
            }

            function push(event, data = {}) {
                if (!enabled) {
                    return;
                }
                events.push({
                    at_iso: new Date().toISOString(),
                    at_ms: Math.round(nowMs()),
                    event,
                    ...data,
                });
                trimEvents();
            }

            function begin(activityId, trigger = "unknown") {
                if (!enabled || !activityId) {
                    return;
                }
                const shouldStart = !session || session.activityId !== activityId || session.completed;
                if (!shouldStart) {
                    return;
                }
                session = {
                    activityId,
                    trigger,
                    startedAt: nowMs(),
                    marks: {},
                    completed: false,
                };
                latestState = {
                    activity_id: activityId,
                    trigger,
                    status: "in_progress",
                    total_ms: null,
                    marks: {},
                    details: {},
                };
                push("session_begin", { activity_id: activityId, trigger });
                notifyUpdate();
            }

            function mark(name, data = {}) {
                if (!enabled || !session) {
                    return;
                }
                if (session.marks[name] === undefined) {
                    session.marks[name] = Math.round(nowMs() - session.startedAt);
                }
                if (latestState) {
                    latestState.marks[name] = session.marks[name];
                    latestState.details[name] = { ...data };
                }
                push(`mark:${name}`, {
                    activity_id: session.activityId,
                    elapsed_ms: session.marks[name],
                    ...data,
                });
                notifyUpdate();
            }

            function end(status = "completed", data = {}) {
                if (!enabled || !session) {
                    return;
                }
                const payload = {
                    activity_id: session.activityId,
                    trigger: session.trigger,
                    status,
                    total_ms: Math.round(nowMs() - session.startedAt),
                    marks: { ...session.marks },
                    ...data,
                };
                push("session_end", payload);
                if (typeof console !== "undefined" && typeof console.info === "function") {
                    console.info("[voting-timing]", payload);
                }
                if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
                    window.dispatchEvent(
                        new CustomEvent("decidero:voting-timing-session", {
                            detail: payload,
                        }),
                    );
                }
                latestState = {
                    activity_id: payload.activity_id,
                    trigger: payload.trigger,
                    status: payload.status,
                    total_ms: payload.total_ms,
                    marks: { ...payload.marks },
                    details: {
                        ...(latestState?.details || {}),
                        ...data,
                    },
                };
                session.completed = true;
                notifyUpdate();
            }

            if (typeof window !== "undefined") {
                window.__decideroVotingTiming = {
                    enabled,
                    getRecent: () => events.slice(),
                    getState: () => (latestState ? { ...latestState, marks: { ...latestState.marks }, details: { ...latestState.details } } : null),
                    clear: () => {
                        events.length = 0;
                        session = null;
                        latestState = null;
                        notifyUpdate();
                    },
                };
            }

            return {
                enabled,
                begin,
                mark,
                end,
                getState: () => (latestState ? { ...latestState, marks: { ...latestState.marks }, details: { ...latestState.details } } : null),
            };
        })();
        let categorizationState = null;
        let categorizationActivityId = null;
        let categorizationRequestInFlight = false;
        let categorizationIsActive = false;
        let activeCategorizationConfig = {};
        let categorizationSelectedBucketId = null;
        let categorizationSelectedItemKey = null;
        let categorizationDraggedItemKey = null;
        let categorizationDraggedBucketId = null;
        const categorizationItemOrder = new Map();
        const transferState = {
            donorActivityId: null,
            donorOrderIndex: null,
            donorToolType: null,
            includeComments: true,
            transformProfile: "standard",
            items: [],
            metadata: {},
            dirty: false,
            loading: false,
            saving: false,
            committing: false,
            autosaveTimer: null,
            active: false,
            loadAttempted: false,
            loadSucceeded: false,
        };


        const activityParticipantState = {
            currentActivityId: null,
            selection: new Set(),
            lastCustomSelection: null,
            availableHighlighted: new Set(),
            selectedHighlighted: new Set(),
            mode: "all",
            dirty: false,
            loading: false,
            lastLoadFailed: false,
        };

        function formatDuration(totalSeconds) {
            const safeSeconds = Math.max(0, Math.floor(totalSeconds || 0));
            const hours = Math.floor(safeSeconds / 3600);
            const minutes = Math.floor((safeSeconds % 3600) / 60);
            const seconds = safeSeconds % 60;
            if (hours > 0) {
                return [hours, minutes, seconds].map(u => String(u).padStart(2, '0')).join(':');
            }
            return [minutes, seconds].map(u => String(u).padStart(2, '0')).join(':');
        }

        function updateActivityTimers() {
            const timers = document.querySelectorAll(".agenda-item-timer");
            const now = Date.now();
            timers.forEach(timer => {
                const startedAtIso = timer.dataset.startedAt;
                let elapsed = parseInt(timer.dataset.baseElapsed, 10) || 0;

                if (startedAtIso) {
                    const startTime = new Date(startedAtIso).getTime();
                    if (!isNaN(startTime)) {
                        const currentRun = Math.max(0, (now - startTime) / 1000);
                        elapsed += currentRun;
                    }
                }
                timer.textContent = formatDuration(elapsed);
            });
        }

        // Start local interval to update timers every second
        setInterval(updateActivityTimers, 1000);

        function setStatus(text, variant) {
            if (ui.statusBadge) {
                ui.statusBadge.textContent = text;
                ui.statusBadge.dataset.statusVariant = variant || "info";
            }
        }

        function showAccessMessage(message) {
            if (!ui.accessNotice) {
                return;
            }
            if (!message) {
                ui.accessNotice.hidden = true;
                ui.accessNotice.textContent = "";
                return;
            }
            ui.accessNotice.hidden = false;
            ui.accessNotice.textContent = message;
        }

        function setAgendaCollapsed(collapsed, { persist = true } = {}) {
            if (!ui.agendaCard || !ui.agendaCollapseToggle) {
                return;
            }
            ui.agendaCard.classList.toggle("is-collapsed", collapsed);
            ui.agendaCollapseToggle.textContent = collapsed ? "Expand" : "Collapse";
            ui.agendaCollapseToggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
            if (persist) {
                try {
                    window.localStorage.setItem("agendaCollapsed", collapsed ? "1" : "0");
                } catch (error) {
                    // Ignore storage errors (private mode, blocked access).
                }
            }
        }

        function updateAgendaSummary() {
            if (!ui.agendaSummaryTotal && !ui.agendaSummaryActive) {
                return;
            }
            const totalCount = state.agenda.length;
            const activeCount = getActiveActivities().length;
            if (ui.agendaSummaryTotal) {
                ui.agendaSummaryTotal.textContent = `${totalCount} ${totalCount === 1 ? "activity" : "activities"}`;
            }
            if (ui.agendaSummaryActive) {
                ui.agendaSummaryActive.textContent = `${activeCount} active`;
            }
        }

        function logEvent(message) {
            if (!ui.eventsLog) {
                return;
            }
            const normalized = (message || "").trim();
            if (normalized === "Heartbeat acknowledged.") {
                return;
            }
            const row = document.createElement("li");
            row.textContent = `[${new Date().toLocaleTimeString()}] ${normalized}`;
            ui.eventsLog.prepend(row);
            const maxItems = Number.parseInt(ui.eventsLog.dataset.maxItems || "25", 10);
            while (ui.eventsLog.children.length > maxItems) {
                ui.eventsLog.removeChild(ui.eventsLog.lastElementChild);
            }
        }

        function updateTransferCountForActivity(activityId, delta = 1) {
            const key = String(activityId || "").trim();
            if (!key || !Number.isFinite(delta) || delta === 0) {
                return;
            }

            let changed = false;
            const applyUpdate = (collection) => {
                if (!Array.isArray(collection)) {
                    return collection;
                }
                return collection.map((item) => {
                    if (!item || item.activity_id !== key) {
                        return item;
                    }
                    const current = Number(item.transfer_count ?? item.transferable_count ?? 0);
                    const safeCurrent = Number.isFinite(current) ? current : 0;
                    const nextCount = Math.max(0, safeCurrent + delta);
                    changed = true;
                    return {
                        ...item,
                        transfer_count: nextCount,
                        transfer_source: nextCount > 0 ? (item.transfer_source || "ideas") : (item.transfer_source || "none"),
                        transfer_reason: nextCount > 0 ? null : (item.transfer_reason || "No ideas to transfer yet."),
                    };
                });
            };

            state.agenda = applyUpdate(state.agenda);
            if (state.latestState && Array.isArray(state.latestState.agenda)) {
                state.latestState.agenda = applyUpdate(state.latestState.agenda);
            }
            if (changed) {
                state.agendaMap = new Map((state.agenda || []).map((item) => [item.activity_id, item]));
                renderAgenda(state.agenda);
                updateAgendaSummary();
            }
        }

        function renderParticipants() {
            if (!ui.participantsList) {
                return;
            }
            ui.participantsList.innerHTML = "";
            if (participants.size === 0) {
                const empty = document.createElement("li");
                empty.textContent = "Waiting for participants…";
                ui.participantsList.appendChild(empty);
                return;
            }

            for (const [connectionId, meta] of participants.entries()) {
                const node = document.createElement("li");
                const fallbackId = connectionId || meta.connectionId;
                const displayName = meta.userId || (fallbackId ? `connection-${String(fallbackId).slice(0, 6)}` : "participant");
                node.textContent = displayName;
                if (meta.userId && meta.userId === context.userId) {
                    node.dataset.self = "true";
                }
                ui.participantsList.appendChild(node);
            }
        }

        function getDisplayName(user) {
            if (!user) {
                return "Unknown";
            }
            const nameParts = [user.first_name || "", user.last_name || ""]
                .map((part) => part && String(part).trim())
                .filter(Boolean);
            if (nameParts.length > 0) {
                return nameParts.join(" ");
            }
            return user.login || user.user_id || "Unknown";
        }

        function getRoleLabel(user) {
            const roleLabel = (user?.role || "participant").toString();
            return roleLabel.charAt(0).toUpperCase() + roleLabel.slice(1);
        }

        function getRoleSortRank(user) {
            const role = (user?.role || "participant").toString().toLowerCase();
            if (role === "super_admin") return 0;
            if (role === "admin") return 1;
            if (role === "facilitator") return 2;
            if (role === "participant") return 3;
            return 4;
        }

        function normalizeSortText(value) {
            return (value || "").toString().trim().toLowerCase();
        }

        function compareUsersByRoleAndName(a, b) {
            const roleDelta = getRoleSortRank(a) - getRoleSortRank(b);
            if (roleDelta !== 0) return roleDelta;

            const aLast = normalizeSortText(a?.last_name);
            const bLast = normalizeSortText(b?.last_name);
            if (aLast !== bLast) return aLast.localeCompare(bLast);

            const aFirst = normalizeSortText(a?.first_name);
            const bFirst = normalizeSortText(b?.first_name);
            if (aFirst !== bFirst) return aFirst.localeCompare(bFirst);

            const aLogin = normalizeSortText(a?.login || a?.user_id);
            const bLogin = normalizeSortText(b?.login || b?.user_id);
            return aLogin.localeCompare(bLogin);
        }

        function setMeetingDirectoryStatus(message, variant = "muted") {
            const statusEl = ui.facilitatorControls.meetingDirectoryStatus;
            if (!statusEl) return;
            statusEl.textContent = message || "";
            statusEl.dataset.variant = message ? variant : "";
        }

        function updateMeetingDirectoryPagination() {
            if (!ui.facilitatorControls.meetingDirectoryPageLabel) return;
            const totalPages = Math.max(1, meetingDirectoryState.pages || 1);
            const currentPage = Math.min(meetingDirectoryState.page, totalPages);
            ui.facilitatorControls.meetingDirectoryPageLabel.textContent = `Page ${currentPage} of ${totalPages}`;
        }

        function updateMeetingAvailableButtons() {
            const availableSelectable = meetingDirectoryState.items.filter(
                (user) => !assignedParticipants.has(user.user_id),
            ).length;
            if (ui.facilitatorControls.meetingDirectoryClearButton) {
                ui.facilitatorControls.meetingDirectoryClearButton.disabled =
                    meetingDirectoryState.highlighted.size === 0;
            }
            if (ui.facilitatorControls.meetingAvailableSelectAll) {
                ui.facilitatorControls.meetingAvailableSelectAll.disabled = availableSelectable === 0;
            }
            if (ui.facilitatorControls.meetingDirectoryPrev) {
                ui.facilitatorControls.meetingDirectoryPrev.disabled =
                    meetingDirectoryState.loading || meetingDirectoryState.page <= 1;
            }
            if (ui.facilitatorControls.meetingDirectoryNext) {
                const totalPages = meetingDirectoryState.pages || 1;
                ui.facilitatorControls.meetingDirectoryNext.disabled =
                    meetingDirectoryState.loading || meetingDirectoryState.page >= totalPages;
            }
        }

        function updateMeetingSelectedButtons() {
            if (ui.facilitatorControls.meetingSelectedSelectAll) {
                ui.facilitatorControls.meetingSelectedSelectAll.disabled = assignedParticipants.size === 0;
            }
            if (ui.facilitatorControls.meetingSelectedStatus) {
                ui.facilitatorControls.meetingSelectedStatus.textContent = assignedParticipants.size
                    ? `${assignedParticipants.size} participant${assignedParticipants.size === 1 ? "" : "s"} selected.`
                    : "No participants selected.";
            }
        }

        function updateMeetingTransferControls() {
            if (ui.facilitatorControls.meetingMoveToSelected) {
                ui.facilitatorControls.meetingMoveToSelected.disabled =
                    meetingDirectoryState.highlighted.size === 0;
            }
            if (ui.facilitatorControls.meetingMoveToAvailable) {
                ui.facilitatorControls.meetingMoveToAvailable.disabled =
                    meetingSelectedHighlights.size === 0;
            }
        }

        function renderMeetingDirectory() {
            const list = ui.facilitatorControls.meetingDirectoryList;
            if (!list) return;
            list.innerHTML = "";

            if (meetingDirectoryState.loading) {
                const row = document.createElement("div");
                row.className = "participant-directory-empty";
                row.textContent = "Loading directory…";
                list.appendChild(row);
                updateMeetingAvailableButtons();
                updateMeetingDirectoryPagination();
                updateMeetingTransferControls();
                return;
            }

            if (!meetingDirectoryState.items.length) {
                const empty = document.createElement("div");
                empty.className = "participant-directory-empty";
                empty.textContent = meetingDirectoryState.searchTerm
                    ? "No users matched your search."
                    : "Search the directory to find users.";
                list.appendChild(empty);
                updateMeetingAvailableButtons();
                updateMeetingDirectoryPagination();
                updateMeetingTransferControls();
                return;
            }

            const sortedItems = [...meetingDirectoryState.items].sort(compareUsersByRoleAndName);
            sortedItems.forEach((item) => {
                const row = document.createElement("div");
                row.className = "participant-directory-row";
                row.tabIndex = 0;
                row.setAttribute("role", "option");
                const alreadySelected = assignedParticipants.has(item.user_id);
                const highlighted = meetingDirectoryState.highlighted.has(item.user_id);

                if (alreadySelected) {
                    row.setAttribute("aria-disabled", "true");
                    row.setAttribute("aria-selected", "false");
                } else {
                    row.removeAttribute("aria-disabled");
                    row.setAttribute("aria-selected", highlighted ? "true" : "false");
                    row.classList.toggle("is-highlighted", highlighted);
                }

                const body = document.createElement("div");
                const avatar = createAvatarNode({
                    name: getDisplayName(item),
                    color: item?.avatar_color,
                    avatarPath: item?.avatar_icon_path,
                });
                const name = document.createElement("div");
                name.className = "participant-directory-name";
                name.textContent = getDisplayName(item);

                const meta = document.createElement("div");
                meta.className = "participant-directory-meta";
                const metaText = document.createElement("span");
                metaText.textContent = [item.login, getRoleLabel(item)].filter(Boolean).join(" • ");
                meta.appendChild(metaText);

                if (item.is_facilitator) {
                    const pill = document.createElement("span");
                    pill.className = "participant-directory-pill";
                    pill.textContent = "Facilitator";
                    meta.appendChild(pill);
                }
                if (alreadySelected) {
                    const pill = document.createElement("span");
                    pill.className = "participant-directory-pill";
                    pill.textContent = "Assigned";
                    meta.appendChild(pill);
                }

                body.appendChild(name);
                body.appendChild(meta);
                row.appendChild(avatar);
                row.appendChild(body);

                if (!alreadySelected) {
                    row.addEventListener("click", () => toggleMeetingAvailableHighlight(item.user_id));
                    row.addEventListener("dblclick", (event) => {
                        event.preventDefault();
                        addMeetingParticipantsFromSelection([item.user_id]);
                    });
                    row.addEventListener("keydown", (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            toggleMeetingAvailableHighlight(item.user_id);
                        }
                        if (event.key === "Enter" && event.metaKey) {
                            addMeetingParticipantsFromSelection([item.user_id]);
                        }
                    });
                }

                list.appendChild(row);
            });

            updateMeetingAvailableButtons();
            updateMeetingDirectoryPagination();
            updateMeetingTransferControls();
        }

        function renderMeetingSelectedList() {
            const list = ui.facilitatorControls.meetingSelectedList;
            if (!list) return;
            list.innerHTML = "";

            if (assignedParticipants.size === 0) {
                const empty = document.createElement("div");
                empty.className = "participant-directory-empty";
                empty.textContent = "No participants selected yet.";
                list.appendChild(empty);
            } else {
                const sortedParticipants = Array.from(assignedParticipants.values()).sort(compareUsersByRoleAndName);
                sortedParticipants.forEach((participant) => {
                    const row = document.createElement("div");
                    row.className = "participant-directory-row participant-directory-row--selected";
                    row.dataset.userId = participant.user_id;
                    row.tabIndex = 0;
                    row.setAttribute("role", "option");
                    const highlighted = meetingSelectedHighlights.has(participant.user_id);
                    row.classList.toggle("is-highlighted", highlighted);
                    row.setAttribute("aria-selected", highlighted ? "true" : "false");

                    const body = document.createElement("div");
                    const avatar = createAvatarNode({
                        name: getDisplayName(participant),
                        color: participant?.avatar_color,
                        avatarPath: participant?.avatar_icon_path,
                    });
                    const name = document.createElement("div");
                    name.className = "participant-directory-name";
                    name.textContent = getDisplayName(participant);

                    const meta = document.createElement("div");
                    meta.className = "participant-directory-meta";
                    const metaText = document.createElement("span");
                    metaText.textContent = getRoleLabel(participant);
                    meta.appendChild(metaText);

                    body.appendChild(name);
                    body.appendChild(meta);
                    row.appendChild(avatar);
                    row.appendChild(body);

                    row.addEventListener("click", () => toggleMeetingSelectedHighlight(participant.user_id));
                    row.addEventListener("dblclick", (event) => {
                        event.preventDefault();
                        removeMeetingParticipantsFromSelection([participant.user_id]);
                    });
                    row.addEventListener("keydown", (event) => {
                        if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            toggleMeetingSelectedHighlight(participant.user_id);
                        }
                    });

                    list.appendChild(row);
                });
            }

            updateMeetingSelectedButtons();
            updateMeetingTransferControls();
        }

        function toggleMeetingAvailableHighlight(userId) {
            if (meetingDirectoryState.highlighted.has(userId)) {
                meetingDirectoryState.highlighted.delete(userId);
            } else {
                meetingDirectoryState.highlighted.add(userId);
            }
            renderMeetingDirectory();
        }

        function toggleMeetingSelectedHighlight(userId) {
            if (meetingSelectedHighlights.has(userId)) {
                meetingSelectedHighlights.delete(userId);
            } else {
                meetingSelectedHighlights.add(userId);
            }
            renderMeetingSelectedList();
        }

        function selectAllMeetingAvailable() {
            const selectable = meetingDirectoryState.items
                .filter((user) => !assignedParticipants.has(user.user_id))
                .map((user) => user.user_id);
            meetingDirectoryState.highlighted = new Set(selectable);
            renderMeetingDirectory();
        }

        function selectAllMeetingSelected() {
            meetingSelectedHighlights.clear();
            assignedParticipants.forEach((_, userId) => meetingSelectedHighlights.add(userId));
            renderMeetingSelectedList();
        }

        async function loadParticipantDirectory({ resetPage = false, silent = false } = {}) {
            if (!state.isFacilitator || !ui.facilitatorControls.meetingDirectoryList) {
                return;
            }
            if (resetPage) {
                meetingDirectoryState.page = 1;
            }
            meetingDirectoryState.loading = true;
            if (!silent) {
                setMeetingDirectoryStatus("Loading directory…", "info");
            }
            renderMeetingDirectory();
            try {
                const params = new URLSearchParams({
                    meeting_id: context.meetingId,
                    page: String(meetingDirectoryState.page),
                    page_size: "25",
                    sort: "name",
                });
                if (meetingDirectoryState.searchTerm) {
                    params.set("q", meetingDirectoryState.searchTerm);
                }
                const resp = await fetch(`/api/users/directory?${params.toString()}`, {
                    credentials: "include",
                });
                if (!resp.ok) {
                    const err = await resp.json().catch(() => ({}));
                    const msg = err?.detail || "Unable to load directory.";
                    throw new Error(msg);
                }
                const payload = await resp.json();
                meetingDirectoryState.items = Array.isArray(payload?.items) ? payload.items : [];
                meetingDirectoryState.pages = payload?.pagination?.pages || 1;
                meetingDirectoryState.total = payload?.pagination?.total || meetingDirectoryState.items.length;
                meetingDirectoryState.highlighted.clear();
                if (!silent) {
                    setMeetingDirectoryStatus(
                        meetingDirectoryState.items.length === 0
                            ? "No users matched your filters."
                            : "Select users and use the arrow to add them.",
                        meetingDirectoryState.items.length === 0 ? "muted" : "success",
                    );
                }
            } catch (error) {
                console.error("Directory load failed:", error);
                setMeetingDirectoryStatus(error.message || "Unable to load directory.", "error");
            } finally {
                meetingDirectoryState.loading = false;
                renderMeetingDirectory();
            }
        }

        function handleParticipantDirectorySearchInput(term) {
            meetingDirectoryState.searchTerm = (term || "").trim();
            if (meetingDirectoryState.debounce) {
                clearTimeout(meetingDirectoryState.debounce);
            }
            meetingDirectoryState.debounce = setTimeout(() => {
                meetingDirectoryState.highlighted.clear();
                loadParticipantDirectory({ resetPage: true });
            }, 300);
        }

        function changeParticipantDirectoryPage(delta) {
            const next = meetingDirectoryState.page + delta;
            if (next < 1) return;
            const totalPages = meetingDirectoryState.pages || 1;
            if (next > totalPages) return;
            meetingDirectoryState.page = next;
            loadParticipantDirectory();
        }

        function clearParticipantDirectorySelection() {
            meetingDirectoryState.highlighted.clear();
            renderMeetingDirectory();
            setMeetingDirectoryStatus("Selection cleared.", "muted");
        }

        async function addMeetingParticipantsFromSelection(userIds = null) {
            const ids = Array.isArray(userIds) && userIds.length > 0
                ? userIds
                : Array.from(meetingDirectoryState.highlighted);
            if (ids.length === 0) {
                return;
            }
            try {
                setMeetingDirectoryStatus("Assigning participants…", "info");
                const resp = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/participants/bulk`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        credentials: "include",
                        body: JSON.stringify({ add: ids }),
                    },
                );
                if (!resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    const msg = typeof data.detail === "string" ? data.detail : "Unable to assign participants.";
                    throw new Error(msg);
                }
                meetingDirectoryState.highlighted.clear();
                meetingSelectedHighlights.clear();
                setMeetingDirectoryStatus("Participants assigned successfully.", "success");
                await loadAssignedParticipants();
                await loadParticipantDirectory({ silent: true });
            } catch (error) {
                console.error("Bulk participant assignment failed:", error);
                setMeetingDirectoryStatus(error.message || "Unable to assign participants.", "error");
            } finally {
                updateMeetingTransferControls();
            }
        }

        async function removeMeetingParticipantsFromSelection(userIds = null) {
            const ids = Array.isArray(userIds) && userIds.length > 0
                ? userIds
                : Array.from(meetingSelectedHighlights);
            if (ids.length === 0) {
                return;
            }
            try {
                setMeetingDirectoryStatus("Removing participants…", "info");
                const resp = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/participants/bulk`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        credentials: "include",
                        body: JSON.stringify({ remove: ids }),
                    },
                );
                if (!resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    const msg = typeof data.detail === "string" ? data.detail : "Unable to remove participants.";
                    throw new Error(msg);
                }
                meetingSelectedHighlights.clear();
                setMeetingDirectoryStatus("Participants removed.", "success");
                await loadAssignedParticipants();
                await loadParticipantDirectory({ silent: true });
            } catch (error) {
                console.error("Bulk participant removal failed:", error);
                setMeetingDirectoryStatus(error.message || "Unable to remove participants.", "error");
            } finally {
                updateMeetingTransferControls();
            }
        }

        function upsertParticipant(connectionId, meta) {
            const id =
                connectionId ||
                meta?.connectionId ||
                meta?.connection_id ||
                meta?.id ||
                meta?.userId;
            if (!id) {
                console.warn("Skipped participant with no connectionId", meta);
                return;
            }
            const normalizedId = String(id);
            participants.set(normalizedId, {
                connectionId: normalizedId,
                userId: meta?.userId || participants.get(normalizedId)?.userId || null,
            });
            renderParticipants();
        }

        function removeParticipant(connectionId) {
            participants.delete(connectionId);
            renderParticipants();
        }

        async function loadAssignedParticipants() {
            try {
                const resp = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/participants`,
                    {
                        credentials: "include",
                    },
                );
                if (!resp.ok) {
                    throw new Error("Unable to load assigned participants");
                }
                const rows = await resp.json();
                assignedParticipants.clear();
                for (const row of rows) {
                    assignedParticipants.set(row.user_id, row);
                }
                meetingSelectedHighlights.clear();
                renderMeetingSelectedList();
                renderMeetingDirectory();
                if (state.isFacilitator && participantDirectoryInitialized) {
                    await loadParticipantDirectory({ silent: true });
                }
                state.activityAssignments.clear();
                const focusActivity = state.selectedActivityId || state.activeActivityId;
                if (state.isFacilitator && focusActivity) {
                    await loadActivityParticipantAssignment(focusActivity, { force: true });
                }
            } catch (error) {
                if (ui.facilitatorControls.participantFeedback) {
                    ui.facilitatorControls.participantFeedback.textContent = String(error.message || error);
                }
            }
        }

        async function addAssignedParticipantByLogin(login) {
            const payload = { login };
            const resp = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/participants`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    credentials: "include",
                    body: JSON.stringify(payload),
                },
            );
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                const msg = typeof data.detail === "string" ? data.detail : "Could not add participant";
                throw new Error(msg);
            }
            await loadAssignedParticipants();
        }

        async function removeAssignedParticipant(userId) {
            const resp = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/participants/${encodeURIComponent(userId)}`,
                {
                    method: "DELETE",
                    credentials: "include",
                },
            );
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                const msg = typeof data.detail === "string" ? data.detail : "Could not remove participant";
                throw new Error(msg);
            }
            await loadAssignedParticipants();
        }

        function resetActivityAssignmentCache() {
            state.activityAssignments.clear();
            activityParticipantState.currentActivityId = null;
            activityParticipantState.selection = new Set();
            activityParticipantState.availableHighlighted = new Set();
            activityParticipantState.selectedHighlighted = new Set();
            activityParticipantState.mode = "all";
            activityParticipantState.dirty = false;
        }

        function setActivityParticipantFeedback(message, variant = "info") {
            if (!ui.facilitatorControls.activityFeedback) {
                return;
            }
            ui.facilitatorControls.activityFeedback.textContent = message || "";
            ui.facilitatorControls.activityFeedback.dataset.variant = message ? variant : "";
        }

        function updateActivityParticipantButtons() {
            const applyButton = ui.facilitatorControls.activityApply;
            if (applyButton) {
                const hasSelection = activityParticipantState.selection.size > 0;
                applyButton.disabled =
                    activityParticipantState.loading ||
                    !state.isFacilitator ||
                    !activityParticipantState.currentActivityId ||
                    !activityParticipantState.dirty ||
                    (!hasSelection && activityParticipantState.mode !== "all");
            }
            const includeAll = ui.facilitatorControls.activityIncludeAll;
            if (includeAll) {
                includeAll.disabled =
                    activityParticipantState.loading ||
                    !state.isFacilitator ||
                    !activityParticipantState.currentActivityId ||
                    (state.activityAssignments.get(activityParticipantState.currentActivityId)?.mode === "all" &&
                        !activityParticipantState.dirty);
            }
            updateActivityTransferControls();
        }

        function updateActivityTransferControls() {
            if (ui.facilitatorControls.activityMoveToSelected) {
                ui.facilitatorControls.activityMoveToSelected.disabled =
                    activityParticipantState.availableHighlighted.size === 0 ||
                    activityParticipantState.loading ||
                    !activityParticipantState.currentActivityId;
            }
            if (ui.facilitatorControls.activityMoveToAvailable) {
                ui.facilitatorControls.activityMoveToAvailable.disabled =
                    activityParticipantState.selectedHighlighted.size === 0 ||
                    activityParticipantState.loading ||
                    !activityParticipantState.currentActivityId;
            }
            if (ui.facilitatorControls.activityAvailableSelectAll) {
                const assignment = state.activityAssignments.get(activityParticipantState.currentActivityId);
                const roster = Array.isArray(assignment?.available_participants) ? assignment.available_participants : [];
                const effectiveSelection = activityParticipantState.dirty
                    ? activityParticipantState.selection
                    : new Set(
                        assignment?.mode === "all"
                            ? roster.map((row) => row.user_id)
                            : assignment?.participant_ids || [],
                    );
                const selectableCount = roster.filter((row) => !effectiveSelection.has(row.user_id)).length;
                ui.facilitatorControls.activityAvailableSelectAll.disabled = selectableCount === 0;
            }
            if (ui.facilitatorControls.activitySelectedSelectAll) {
                ui.facilitatorControls.activitySelectedSelectAll.disabled =
                    activityParticipantState.selection.size === 0;
            }
        }

        function renderActivityParticipantSection(activityId) {
            const container = ui.facilitatorControls.activityAdmin;
            if (!container) {
                return;
            }
            const modalIsActive =
                ui.participantAdminModal &&
                !ui.participantAdminModal.hidden &&
                ui.activityRosterPanel &&
                !ui.activityRosterPanel.hidden;
            if (!activityId && modalIsActive && activityParticipantState.currentActivityId) {
                activityId = activityParticipantState.currentActivityId;
            }
            if (ui.activityRosterPanel && !ui.activityRosterPanel.hidden) {
                updateParticipantModalActivityMeta(activityId);
            }
            if (!state.isFacilitator || !activityId) {
                container.hidden = true;
                activityParticipantState.currentActivityId = null;
                activityParticipantState.selection = new Set();
                activityParticipantState.availableHighlighted = new Set();
                activityParticipantState.selectedHighlighted = new Set();
                activityParticipantState.mode = "all";
                activityParticipantState.dirty = false;
                updateActivityParticipantButtons();
                return;
            }
            container.hidden = false;

            if (activityParticipantState.currentActivityId !== activityId) {
                activityParticipantState.currentActivityId = activityId;
                activityParticipantState.selection = new Set();
                activityParticipantState.availableHighlighted = new Set();
                activityParticipantState.selectedHighlighted = new Set();
                activityParticipantState.mode = "all";
                activityParticipantState.dirty = false;
            }

            const assignment = state.activityAssignments.get(activityId);
            const list = ui.facilitatorControls.activityList;
            if (!assignment) {
                if (list) {
                    list.innerHTML = "";
                    const placeholder = document.createElement("li");
                    placeholder.textContent = activityParticipantState.lastLoadFailed
                        ? "Unable to load activity participants. Refresh or log in again."
                        : "Loading activity participants…";
                    list.appendChild(placeholder);
                }
                if (!activityParticipantState.loading && !activityParticipantState.lastLoadFailed) {
                    loadActivityParticipantAssignment(activityId);
                }
                updateActivityParticipantButtons();
                return;
            }

            const roster = Array.isArray(assignment.available_participants)
                ? assignment.available_participants
                : [];
            const effectiveSelection =
                activityParticipantState.dirty || activityParticipantState.mode !== assignment.mode
                    ? activityParticipantState.selection
                    : new Set(
                        assignment.mode === "all"
                            ? roster.map((row) => row.user_id)
                            : assignment.participant_ids || [],
                    );

            if (!activityParticipantState.dirty) {
                activityParticipantState.mode = assignment.mode;
                activityParticipantState.selection = new Set(effectiveSelection);
            }

            const rosterById = new Map(roster.map((row) => [row.user_id, row]));
            activityParticipantState.availableHighlighted = new Set(
                Array.from(activityParticipantState.availableHighlighted).filter(
                    (id) => rosterById.has(id) && !effectiveSelection.has(id),
                ),
            );
            activityParticipantState.selectedHighlighted = new Set(
                Array.from(activityParticipantState.selectedHighlighted).filter((id) => effectiveSelection.has(id)),
            );

            if (list) {
                list.innerHTML = "";
                if (roster.length === 0) {
                    const empty = document.createElement("div");
                    empty.className = "participant-directory-empty";
                    empty.textContent =
                        "No meeting participants are assigned yet. Add participants above to configure this activity.";
                    list.appendChild(empty);
                } else {
                    roster.forEach((row) => {
                        const item = document.createElement("div");
                        item.className = "participant-directory-row";
                        item.tabIndex = 0;
                        item.setAttribute("role", "option");
                        const alreadySelected = effectiveSelection.has(row.user_id);
                        const highlighted = activityParticipantState.availableHighlighted.has(row.user_id);

                        if (alreadySelected) {
                            item.setAttribute("aria-disabled", "true");
                            item.setAttribute("aria-selected", "false");
                        } else {
                            item.removeAttribute("aria-disabled");
                            item.setAttribute("aria-selected", highlighted ? "true" : "false");
                            item.classList.toggle("is-highlighted", highlighted);
                        }

                        const body = document.createElement("div");
                        const avatar = createAvatarNode({
                            name: getDisplayName(row),
                            color: row?.avatar_color,
                            avatarPath: row?.avatar_icon_path,
                        });
                        const name = document.createElement("div");
                        name.className = "participant-directory-name";
                        name.textContent = getDisplayName(row);
                        const meta = document.createElement("div");
                        meta.className = "participant-directory-meta";
                        const metaText = document.createElement("span");
                        metaText.textContent = getRoleLabel(row);
                        meta.appendChild(metaText);
                        body.appendChild(name);
                        body.appendChild(meta);
                        item.appendChild(avatar);
                        item.appendChild(body);

                        if (!alreadySelected) {
                            item.addEventListener("click", () => toggleActivityAvailableHighlight(row.user_id));
                            item.addEventListener("dblclick", (event) => {
                                event.preventDefault();
                                addActivityParticipantsFromAvailable([row.user_id]);
                            });
                            item.addEventListener("keydown", (event) => {
                                if (event.key === "Enter" || event.key === " ") {
                                    event.preventDefault();
                                    toggleActivityAvailableHighlight(row.user_id);
                                }
                            });
                        }

                        list.appendChild(item);
                    });
                }
            }

            if (ui.facilitatorControls.activitySelectedList) {
                const selectedList = ui.facilitatorControls.activitySelectedList;
                selectedList.innerHTML = "";
                if (roster.length === 0) {
                    const empty = document.createElement("div");
                    empty.className = "participant-directory-empty";
                    empty.textContent = "No participants available yet.";
                    selectedList.appendChild(empty);
                } else if (effectiveSelection.size === 0) {
                    const empty = document.createElement("div");
                    empty.className = "participant-directory-empty";
                    empty.textContent = "Select participants to assign.";
                    selectedList.appendChild(empty);
                } else {
                    Array.from(effectiveSelection).forEach((userId) => {
                        const row = rosterById.get(userId);
                        const item = document.createElement("div");
                        item.className = "participant-directory-row participant-directory-row--selected";
                        item.tabIndex = 0;
                        item.setAttribute("role", "option");
                        const highlighted = activityParticipantState.selectedHighlighted.has(userId);
                        item.classList.toggle("is-highlighted", highlighted);
                        item.setAttribute("aria-selected", highlighted ? "true" : "false");

                        const body = document.createElement("div");
                        const avatar = createAvatarNode({
                            name: row ? getDisplayName(row) : userId,
                            color: row?.avatar_color,
                            avatarPath: row?.avatar_icon_path,
                        });
                        const name = document.createElement("div");
                        name.className = "participant-directory-name";
                        name.textContent = row ? getDisplayName(row) : userId;
                        const meta = document.createElement("div");
                        meta.className = "participant-directory-meta";
                        const metaText = document.createElement("span");
                        metaText.textContent = row ? getRoleLabel(row) : "Participant";
                        meta.appendChild(metaText);
                        body.appendChild(name);
                        body.appendChild(meta);
                        item.appendChild(avatar);
                        item.appendChild(body);

                        item.addEventListener("click", () => toggleActivitySelectedHighlight(userId));
                        item.addEventListener("dblclick", (event) => {
                            event.preventDefault();
                            removeActivityParticipantsFromSelected([userId]);
                        });
                        item.addEventListener("keydown", (event) => {
                            if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                toggleActivitySelectedHighlight(userId);
                            }
                        });

                        selectedList.appendChild(item);
                    });
                }
            }

            const hint = container.querySelector(".activity-participant-hint");
            if (hint) {
                const hintMode = activityParticipantState.dirty ? "custom" : assignment.mode;
                hint.textContent =
                    hintMode === "all"
                        ? "Everyone in the meeting will join unless you remove participants below."
                        : "Only the selected participants will join when this activity runs.";
            }

            if (ui.facilitatorControls.activityReuse) {
                ui.facilitatorControls.activityReuse.hidden = !activityParticipantState.lastCustomSelection;
            }

            setActivityParticipantFeedback("");
            updateActivityParticipantButtons();
        }

        async function loadActivityParticipantAssignment(activityId, { force = false } = {}) {
            if (!state.isFacilitator || !activityId) {
                return;
            }
            if (!force && state.activityAssignments.has(activityId)) {
                renderActivityParticipantSection(activityId);
                return;
            }

            activityParticipantState.loading = true;
            activityParticipantState.lastLoadFailed = false;
            updateActivityParticipantButtons();

            try {
                const resp = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/agenda/${encodeURIComponent(activityId)}/participants`,
                    { credentials: "include" },
                );
                if (!resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    throw new Error(
                        typeof data.detail === "string"
                            ? data.detail
                            : "Unable to load activity participant assignment.",
                    );
                }
                const assignment = await resp.json();
                state.activityAssignments.set(activityId, assignment);
                activityParticipantState.mode = assignment.mode;
                activityParticipantState.selection = new Set(
                    assignment.mode === "all"
                        ? (assignment.available_participants || []).map((row) => row.user_id)
                        : assignment.participant_ids || [],
                );
                activityParticipantState.availableHighlighted = new Set();
                activityParticipantState.selectedHighlighted = new Set();
                activityParticipantState.dirty = false;
                setActivityParticipantFeedback("");
            } catch (error) {
                activityParticipantState.lastLoadFailed = true;
                console.error("Failed to load activity participant assignment:", error);
                setActivityParticipantFeedback(
                    error.message || "Unable to load activity participant assignment.",
                    "error",
                );
            } finally {
                activityParticipantState.loading = false;
                renderActivityParticipantSection(activityId);
            }
        }

        async function applyActivityParticipantSelection(modeOverride = null) {
            const activityId = activityParticipantState.currentActivityId;
            if (!state.isFacilitator || !activityId || activityParticipantState.loading) {
                return;
            }

            const mode = modeOverride || activityParticipantState.mode;
            const selectedIds = Array.from(activityParticipantState.selection);
            if (mode !== "all" && selectedIds.length === 0) {
                setActivityParticipantFeedback(
                    "Select at least one participant or include everyone for this activity.",
                    "error",
                );
                return;
            }

            activityParticipantState.loading = true;
            updateActivityParticipantButtons();
            setActivityParticipantFeedback("", "info");

            try {
                const payload =
                    mode === "all"
                        ? { mode: "all" }
                        : { mode: "custom", participant_ids: selectedIds };
                const resp = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/agenda/${encodeURIComponent(activityId)}/participants`,
                    {
                        method: "PUT",
                        credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    },
                );
                if (!resp.ok) {
                    const data = await resp.json().catch(() => ({}));
                    const error = new Error(
                        typeof data.detail === "string"
                            ? data.detail
                            : "Unable to update activity participant assignment.",
                    );
                    if (resp.status === 409) {
                        error.isConflict = true;
                        error.conflictDetails = data.conflict_details || data.conflictDetails || null;
                    }
                    throw error;
                }
                const assignment = await resp.json();
                state.activityAssignments.set(activityId, assignment);
                activityParticipantState.mode = assignment.mode;
                activityParticipantState.selection = new Set(
                    assignment.mode === "all"
                        ? (assignment.available_participants || []).map((row) => row.user_id)
                        : assignment.participant_ids || [],
                );
                if (assignment.mode === "custom" && assignment.participant_ids && assignment.participant_ids.length > 0) {
                    activityParticipantState.lastCustomSelection = new Set(assignment.participant_ids);
                }
                activityParticipantState.dirty = false;
                setActivityParticipantFeedback("Activity participant list updated.", "success");
            } catch (error) {
                console.error("Failed to update activity participant assignment:", error);
                if (error.isConflict && error.conflictDetails) {
                    const conflicting = error.conflictDetails.conflicting_users || [];
                    const names = conflicting
                        .map((user) => user.display_name || user.login || user.user_id)
                        .filter(Boolean)
                        .join(", ");
                    const message =
                        names.length > 0
                            ? `Roster change blocked. Conflicts with: ${names}.`
                            : "Roster change blocked by participant conflicts in another active activity.";
                    setActivityParticipantFeedback(message, "error");
                } else {
                    setActivityParticipantFeedback(
                        error.message || "Unable to update activity participant assignment.",
                        "error",
                    );
                }
            } finally {
                activityParticipantState.loading = false;
                renderActivityParticipantSection(activityId);
            }
        }

        function toggleActivityAvailableHighlight(userId) {
            if (activityParticipantState.availableHighlighted.has(userId)) {
                activityParticipantState.availableHighlighted.delete(userId);
            } else {
                activityParticipantState.availableHighlighted.add(userId);
            }
            renderActivityParticipantSection(activityParticipantState.currentActivityId);
        }

        function toggleActivitySelectedHighlight(userId) {
            if (activityParticipantState.selectedHighlighted.has(userId)) {
                activityParticipantState.selectedHighlighted.delete(userId);
            } else {
                activityParticipantState.selectedHighlighted.add(userId);
            }
            renderActivityParticipantSection(activityParticipantState.currentActivityId);
        }

        function selectAllActivityAvailable() {
            const assignment = state.activityAssignments.get(activityParticipantState.currentActivityId);
            const roster = Array.isArray(assignment?.available_participants) ? assignment.available_participants : [];
            const effectiveSelection = activityParticipantState.dirty
                ? activityParticipantState.selection
                : new Set(
                    assignment?.mode === "all"
                        ? roster.map((row) => row.user_id)
                        : assignment?.participant_ids || [],
                );
            const selectable = roster
                .filter((row) => !effectiveSelection.has(row.user_id))
                .map((row) => row.user_id);
            activityParticipantState.availableHighlighted = new Set(selectable);
            renderActivityParticipantSection(activityParticipantState.currentActivityId);
        }

        function selectAllActivitySelected() {
            activityParticipantState.selectedHighlighted = new Set(activityParticipantState.selection);
            renderActivityParticipantSection(activityParticipantState.currentActivityId);
        }

        function addActivityParticipantsFromAvailable(userIds = null) {
            const ids = Array.isArray(userIds) && userIds.length > 0
                ? userIds
                : Array.from(activityParticipantState.availableHighlighted);
            if (ids.length === 0) {
                return;
            }
            const nextSelection = new Set(activityParticipantState.selection);
            ids.forEach((userId) => nextSelection.add(userId));
            activityParticipantState.selection = nextSelection;
            activityParticipantState.mode = "custom";
            activityParticipantState.dirty = true;
            activityParticipantState.availableHighlighted.clear();
            activityParticipantState.selectedHighlighted.clear();
            renderActivityParticipantSection(activityParticipantState.currentActivityId);
        }

        function removeActivityParticipantsFromSelected(userIds = null) {
            const ids = Array.isArray(userIds) && userIds.length > 0
                ? userIds
                : Array.from(activityParticipantState.selectedHighlighted);
            if (ids.length === 0) {
                return;
            }
            const nextSelection = new Set(activityParticipantState.selection);
            ids.forEach((userId) => nextSelection.delete(userId));
            activityParticipantState.selection = nextSelection;
            activityParticipantState.mode = "custom";
            activityParticipantState.dirty = true;
            activityParticipantState.availableHighlighted.clear();
            activityParticipantState.selectedHighlighted.clear();
            renderActivityParticipantSection(activityParticipantState.currentActivityId);
        }

        function formatValue(value, fallback = "—") {
            if (value === null || value === undefined || value === "") {
                return fallback;
            }
            if (typeof value === "object") {
                try {
                    return JSON.stringify(value);
                } catch (error) {
                    return fallback;
                }
            }
            return String(value);
        }

        function renderMetadata(metadata) {
            if (!ui.state.metadata) {
                return;
            }
            ui.state.metadata.innerHTML = "";
            const entries = Object.entries(metadata || {});
            if (entries.length === 0) {
                ui.state.metadata.textContent = "No additional context yet.";
                return;
            }

            const fragment = document.createDocumentFragment();
            entries.slice(0, 6).forEach(([key, value]) => {
                const row = document.createElement("div");
                const label = document.createElement("strong");
                label.textContent = `${key}: `;
                const span = document.createElement("span");
                span.textContent = formatValue(value, "—");
                row.append(label, span);
                fragment.appendChild(row);
            });
            if (entries.length > 6) {
                const extra = document.createElement("div");
                extra.textContent = `…plus ${entries.length - 6} more`;
                fragment.appendChild(extra);
            }
            ui.state.metadata.appendChild(fragment);
        }

        function resolveActivityContext(snapshot, activityId) {
            if (!activityId) {
                return null;
            }
            const activity = state.agendaMap.get(activityId) || null;
            const activeEntry = state.activeActivities?.[activityId] || null;
            const isLegacyCurrent = snapshot?.currentActivity === activityId;
            const legacyMetadata = isLegacyCurrent ? snapshot?.metadata || {} : {};
            const legacyTool = isLegacyCurrent ? snapshot?.currentTool : null;
            const legacyStatus = isLegacyCurrent ? snapshot?.status : null;
            const entry =
                activeEntry ||
                (isLegacyCurrent
                    ? { status: legacyStatus, tool: legacyTool, metadata: legacyMetadata }
                    : null);

            const status = String(entry?.status || "").toLowerCase();
            const isActive = status === "in_progress" || status === "paused";
            const toolType = String(entry?.tool || activity?.tool_type || legacyTool || "").toLowerCase();
            const metadata = entry?.metadata || legacyMetadata || {};
            const participantScope = (metadata.participantScope || metadata.participant_scope || "").toLowerCase();
            const metadataIds = metadata.participantIds || metadata.participant_ids;
            const scopedIds = Array.isArray(metadataIds)
                ? metadataIds.map((id) => String(id)).filter(Boolean)
                : [];

            let assignmentMode = participantScope === "custom" || scopedIds.length > 0 ? "custom" : "all";
            let allowedIds = assignmentMode === "custom" ? new Set(scopedIds) : new Set();

            if (assignmentMode !== "custom" && activity && Array.isArray(activity.config?.participant_ids)) {
                const configured = activity.config.participant_ids
                    .map((id) => String(id))
                    .filter(Boolean);
                if (configured.length > 0) {
                    assignmentMode = "custom";
                    allowedIds = new Set(configured);
                }
            }

            const accessState = getActivityAccessState(activity, entry, isActive);
            const restricted =
                Boolean(activityId && toolType) &&
                assignmentMode === "custom" &&
                !state.isFacilitator &&
                Boolean(context.userId) &&
                !allowedIds.has(context.userId);
            const hasActiveTool = Boolean(activityId && toolType && isActive);
            const canUseTool = Boolean(activityId && toolType && (state.isFacilitator ? true : (!restricted && isActive)));

            return {
                activityId,
                activity,
                toolType,
                assignmentMode,
                accessState,
                hasActiveTool,
                canUseTool,
                restricted,
                isActive,
            };
        }

        function resolveSelectedActivityContext(snapshot) {
            const candidates = [];
            if (state.selectedActivityId) {
                candidates.push(state.selectedActivityId);
            }
            const currentId = snapshot?.currentActivity || null;
            if (currentId && !candidates.includes(currentId)) {
                candidates.push(currentId);
            }

            if (!state.isFacilitator) {
                state.agenda.forEach((item) => {
                    if (candidates.includes(item.activity_id)) {
                        return;
                    }
                    const entry = state.activeActivities?.[item.activity_id];
                    if (!entry || typeof entry !== "object") {
                        return;
                    }
                    const status = String(entry.status || "").toLowerCase();
                    if (status !== "in_progress" && status !== "paused") {
                        return;
                    }
                    candidates.push(item.activity_id);
                });
            }

            let fallback = null;
            for (const id of candidates) {
                const context = resolveActivityContext(snapshot, id);
                if (!context) {
                    continue;
                }
                if (!fallback) {
                    fallback = context;
                }
                if (context.accessState?.canEnter) {
                    return context;
                }
            }
            return fallback;
        }

        function updateParticipantStatus(eligibility) {
            if (!ui.meetingOverview) {
                return;
            }

            const meetingTitle = state.meeting?.title || ui.meetingOverview.title?.textContent || "This meeting";
            const meetingDescription =
                (state.meeting?.description || "").trim() || "No description provided yet.";
            if (ui.meetingOverview.title) {
                ui.meetingOverview.title.textContent = meetingTitle;
            }
            if (ui.meetingOverview.description) {
                ui.meetingOverview.description.textContent = meetingDescription;
            }
            const facilitatorNames =
                (state.meeting?.facilitator_names && state.meeting.facilitator_names.filter(Boolean)) ||
                (state.meeting?.facilitators && state.meeting.facilitators.map((facilitator) => facilitator?.name).filter(Boolean)) ||
                [];
            if (ui.meetingOverview.facilitator) {
                ui.meetingOverview.facilitator.textContent = facilitatorNames.length
                    ? facilitatorNames.join(", ")
                    : "—";
            }

            const hasActiveTool = eligibility?.hasActiveTool;
            const isActive = hasActiveTool && eligibility?.canUseTool;
            const restricted = eligibility?.restricted;
            state.participantStage = isActive ? "active" : restricted ? "restricted" : "waiting";

            if (ui.meetingOverview.statusTitle) {
                ui.meetingOverview.statusTitle.textContent = isActive ? "You're in the activity" : "Waiting to join";
            }

            if (ui.meetingOverview.statusBadge) {
                ui.meetingOverview.statusBadge.textContent = isActive ? "In progress" : "Waiting";
                ui.meetingOverview.statusBadge.dataset.variant = isActive ? "active" : "muted";
            }

            if (root) {
                root.dataset.participantStage = state.participantStage;
            }
        }

        function renderState(snapshot) {
            if (!snapshot) {
                if (ui.state.status) {
                    ui.state.status.textContent = "No live updates yet.";
                }
                if (ui.state.activity) {
                    ui.state.activity.textContent = "—";
                }
                if (ui.state.tool) {
                    ui.state.tool.textContent = "—";
                }
                if (ui.state.updated) {
                    ui.state.updated.textContent = "—";
                }
                renderMetadata(null);
                return;
            }

            if (ui.state.status) {
                ui.state.status.textContent = formatValue(snapshot.status, "Pending");
            }
            if (ui.state.activity) {
                ui.state.activity.textContent = formatValue(snapshot.currentActivity, "—");
            }
            if (ui.state.tool) {
                ui.state.tool.textContent = formatValue(snapshot.currentTool, "—");
            }
            if (ui.state.updated) {
                const timestamp = snapshot.updatedAt
                    ? new Date(snapshot.updatedAt).toLocaleTimeString()
                    : new Date().toLocaleTimeString();
                ui.state.updated.textContent = timestamp;
            }
            renderMetadata(snapshot.metadata);
        }

        function formatTimestamp(isoString) {
            if (!isoString) {
                return new Date().toLocaleTimeString();
            }
            const date = new Date(isoString);
            if (Number.isNaN(date.getTime())) {
                return isoString;
            }
            return `${date.toLocaleDateString()} ${date.toLocaleTimeString()}`;
        }

        function formatIdeaTimestamp(isoString) {
            const fallback = new Date();
            const date = isoString ? new Date(isoString) : fallback;
            if (Number.isNaN(date.getTime())) {
                return "";
            }
            const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
            const today = new Date();
            const isToday = date.toDateString() === today.toDateString();
            return isToday ? time : `${date.toLocaleDateString()} ${time}`;
        }

        function coerceConfigBool(value) {
            if (typeof value === "boolean") {
                return value;
            }
            if (typeof value === "number") {
                return value !== 0;
            }
            if (typeof value === "string") {
                const normalized = value.trim().toLowerCase();
                if (["true", "1", "yes", "on"].includes(normalized)) {
                    return true;
                }
                if (["false", "0", "no", "off", ""].includes(normalized)) {
                    return false;
                }
            }
            return Boolean(value);
        }

        function getBrainstormingAutoJumpStorageKey() {
            const userId = context.userId || "anonymous";
            return `brainstorming:autoJump:${context.meetingId}:${userId}`;
        }

        function getBrainstormingAutoJumpPreference() {
            if (!brainstorming.autoJumpToggle) {
                return coerceConfigBool(activeBrainstormingConfig.auto_jump_new_ideas ?? true);
            }
            const stored = localStorage.getItem(getBrainstormingAutoJumpStorageKey());
            if (stored === "true" || stored === "false") {
                return stored === "true";
            }
            return coerceConfigBool(activeBrainstormingConfig.auto_jump_new_ideas ?? true);
        }

        function syncBrainstormingAutoJumpToggle() {
            if (!brainstorming.autoJumpToggle) {
                return;
            }
            const stored = localStorage.getItem(getBrainstormingAutoJumpStorageKey());
            const desired = stored === null
                ? coerceConfigBool(activeBrainstormingConfig.auto_jump_new_ideas ?? true)
                : stored === "true";
            brainstorming.autoJumpToggle.checked = desired;
        }

        function renderBrainstormingEmptyRow() {
            if (!brainstorming.ideasBody) {
                return;
            }
            const row = document.createElement("tr");
            row.className = "brainstorming-empty-row";
            const cell = document.createElement("td");
            cell.colSpan = 5;
            cell.textContent = "No ideas yet. Be the first to share!";
            row.appendChild(cell);
            brainstorming.ideasBody.appendChild(row);
        }

        function resetBrainstormingIdeas() {
            if (!brainstorming.ideasBody) {
                return;
            }
            brainstorming.ideasBody.innerHTML = "";
            brainstormingIdeaIds.clear();
            brainstormingIdeaNumbers.clear();
            brainstormingSubcommentCounts.clear();
            brainstormingIdeaCount = 0;
            renderBrainstormingEmptyRow();
        }

        function renderIdeas(ideas) {
            if (!brainstorming.ideasBody) {
                return;
            }
            brainstorming.ideasBody.innerHTML = "";
            brainstormingIdeaIds.clear();
            brainstormingIdeaNumbers.clear();
            brainstormingSubcommentCounts.clear();
            brainstormingIdeaCount = 0;
            if (!ideas || ideas.length === 0) {
                renderBrainstormingEmptyRow();
                return;
            }

            // Separate top-level ideas and subcomments
            const topLevelIdeas = ideas.filter((idea) => !idea.parent_id);
            const subcommentsByParent = new Map();
            ideas.forEach((idea) => {
                if (idea.parent_id) {
                    if (!subcommentsByParent.has(idea.parent_id)) {
                        subcommentsByParent.set(idea.parent_id, []);
                    }
                    subcommentsByParent.get(idea.parent_id).push(idea);
                }
            });

            topLevelIdeas.sort((a, b) => {
                const aTime = new Date(a.timestamp || 0).getTime() || 0;
                const bTime = new Date(b.timestamp || 0).getTime() || 0;
                if (aTime !== bTime) {
                    return aTime - bTime;
                }
                const aId = Number(a.id ?? a.idea_id ?? 0) || 0;
                const bId = Number(b.id ?? b.idea_id ?? 0) || 0;
                return aId - bId;
            });

            topLevelIdeas.forEach((idea) => {
                const subcomments = subcommentsByParent.get(idea.id) || [];
                appendIdea(idea, { prepend: false, subcomments, applyScroll: false });
            });
            ensureReplyButtons();
        }

        function getIdeaAuthorName(idea) {
            const anonymised = coerceConfigBool(activeBrainstormingConfig.allow_anonymous);
            if (anonymised) {
                return "Anonymous";
            }
            return idea.submitted_name || idea.user_id || "Anonymous";
        }

        function normalizeUserColor(value) {
            if (typeof value !== "string") {
                return null;
            }
            const normalized = value.trim();
            if (!/^#[0-9a-fA-F]{6}$/.test(normalized)) {
                return null;
            }
            return normalized;
        }

        function getIdeaAuthorColor(idea) {
            const anonymised = coerceConfigBool(activeBrainstormingConfig.allow_anonymous);
            if (anonymised) {
                return null;
            }
            return normalizeUserColor(idea?.user_color);
        }

        function normalizeAvatarPath(value) {
            if (typeof value !== "string") {
                return null;
            }
            const normalized = value.trim();
            if (!normalized) {
                return null;
            }
            if (!normalized.startsWith("/static/avatars/fluent/icons/")) {
                return null;
            }
            if (!normalized.endsWith(".svg")) {
                return null;
            }
            return normalized;
        }

        function getIdeaAuthorAvatarPath(idea) {
            const anonymised = coerceConfigBool(activeBrainstormingConfig.allow_anonymous);
            if (anonymised) {
                return null;
            }
            return normalizeAvatarPath(idea?.user_avatar_icon_path);
        }

        function computeAvatarInitials(name) {
            const trimmed = String(name || "").trim();
            if (!trimmed) {
                return "U";
            }
            const parts = trimmed.split(/\s+/).filter(Boolean);
            if (parts.length >= 2) {
                return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
            }
            return trimmed.slice(0, 2).toUpperCase();
        }

        function createAvatarNode({ name, color, avatarPath, className = "" }) {
            const avatar = document.createElement("span");
            avatar.className = className || "participant-directory-avatar";
            const safeColor = normalizeUserColor(color);
            if (safeColor) {
                avatar.style.backgroundColor = safeColor;
            }

            const safePath = normalizeAvatarPath(avatarPath);
            if (safePath) {
                const img = document.createElement("img");
                img.src = safePath;
                img.alt = "";
                img.loading = "lazy";
                avatar.appendChild(img);
                avatar.setAttribute("aria-hidden", "true");
                return avatar;
            }

            avatar.textContent = computeAvatarInitials(name);
            avatar.setAttribute("aria-hidden", "true");
            return avatar;
        }

        function renderAuthorCell(authorCell, authorName, userColor, userAvatarPath = null) {
            if (!authorCell) {
                return;
            }
            authorCell.textContent = "";
            const wrap = document.createElement("span");
            wrap.className = "idea-author-wrap";

            const avatar = createAvatarNode({
                name: authorName,
                color: userColor,
                avatarPath: userAvatarPath,
                className: "idea-author-avatar",
            });
            wrap.appendChild(avatar);

            const label = document.createElement("span");
            label.className = "idea-author-name";
            label.textContent = authorName || "—";
            wrap.appendChild(label);
            authorCell.appendChild(wrap);
        }

        function ensureReplyButtons() {
            if (!brainstorming.ideasBody) {
                return;
            }
            const shouldShow =
                coerceConfigBool(activeBrainstormingConfig.allow_subcomments) && brainstormingActive;
            const rows = brainstorming.ideasBody.querySelectorAll(".brainstorming-idea-row");
            rows.forEach((row) => {
                const ideaId = row.dataset.ideaId;
                const textCell = row.querySelector(".idea-col-text");
                if (!textCell || !ideaId) {
                    return;
                }
                const existing = textCell.querySelector(".brainstorming-reply-btn");
                if (shouldShow) {
                    if (!existing) {
                        const replyBtn = document.createElement("button");
                        replyBtn.type = "button";
                        replyBtn.className = "control-btn brainstorming-reply-btn";
                        replyBtn.textContent = "Reply";
                        replyBtn.addEventListener("click", (e) => {
                            e.stopPropagation();
                            showSubcommentForm(ideaId, row);
                        });
                        textCell.appendChild(replyBtn);
                    }
                } else if (existing) {
                    existing.remove();
                }
            });
        }

        let activeSubcommentForm = null;

        function showSubcommentForm(parentId, containerEl) {
            // Remove any existing subcomment form
            if (activeSubcommentForm) {
                activeSubcommentForm.remove();
                activeSubcommentForm = null;
            }

            const formRow = document.createElement("tr");
            formRow.className = "subcomment-form-row";
            const formCell = document.createElement("td");
            formCell.colSpan = 5;
            const form = document.createElement("div");
            form.className = "subcomment-form";
            form.innerHTML = `
                <textarea class="subcomment-input" placeholder="Add a comment..." rows="2"></textarea>
                <div class="subcomment-actions">
                    <button type="button" class="control-btn subcomment-cancel">Cancel</button>
                    <button type="button" class="control-btn primary subcomment-submit">Reply</button>
                </div>
            `;
            formCell.appendChild(form);
            formRow.appendChild(formCell);

            const textarea = form.querySelector(".subcomment-input");
            const cancelBtn = form.querySelector(".subcomment-cancel");
            const submitBtn = form.querySelector(".subcomment-submit");

            const handleSubcommentSubmit = async () => {
                const content = textarea.value.trim();
                if (!content || submitBtn.disabled) {
                    return;
                }

                submitBtn.disabled = true;
                try {
                    await submitSubcomment(content, parentId);
                    formRow.remove();
                    activeSubcommentForm = null;
                } catch (error) {
                    setBrainstormingError(error.message || "Unable to submit comment.");
                } finally {
                    submitBtn.disabled = false;
                }
            };

            cancelBtn.addEventListener("click", () => {
                formRow.remove();
                activeSubcommentForm = null;
            });

            submitBtn.addEventListener("click", handleSubcommentSubmit);
            textarea.addEventListener("keydown", (event) => {
                if (event.isComposing || event.key !== "Enter" || event.shiftKey) {
                    return;
                }
                event.preventDefault();
                handleSubcommentSubmit();
            });

            if (containerEl && containerEl.parentNode) {
                containerEl.insertAdjacentElement("afterend", formRow);
            } else if (brainstorming.ideasBody) {
                brainstorming.ideasBody.appendChild(formRow);
            }
            activeSubcommentForm = formRow;
            textarea.focus();
        }

        async function submitSubcomment(content, parentId) {
            if (!brainstormingActivityId) {
                throw new Error("No active brainstorming activity selected.");
            }
            const payload = { content, parent_id: parentId };
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/brainstorming/ideas?activity_id=${encodeURIComponent(brainstormingActivityId)}`,
                {
                    method: "POST",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload),
                },
            );
            if (!response.ok) {
                const errorPayload = await response.json().catch(() => ({}));
                throw new Error(errorPayload.detail || "Unable to submit comment");
            }
            const createdIdea = await response.json();
            // Find parent container and append subcomment
            if (brainstorming.ideasBody) {
                appendSubcomment(createdIdea);
            }
        }

        function appendSubcomment(idea) {
            const ideaId = idea.id ?? idea.idea_id;
            if (ideaId && brainstormingIdeaIds.has(ideaId)) {
                return;
            }

            if (!brainstorming.ideasBody) {
                return;
            }

            const row = document.createElement("tr");
            row.className = "brainstorming-subcomment-row";
            row.dataset.ideaId = ideaId;
            if (idea.parent_id) {
                row.dataset.parentId = idea.parent_id;
            }

            const parentId = idea.parent_id;
            let subcommentNumber = "";
            if (parentId) {
                if (!brainstormingSubcommentCounts.has(parentId)) {
                    const existingReplies = brainstorming.ideasBody.querySelectorAll(
                        `[data-parent-id="${parentId}"]`,
                    );
                    brainstormingSubcommentCounts.set(parentId, existingReplies.length);
                }
                const nextIndex = (brainstormingSubcommentCounts.get(parentId) || 0) + 1;
                brainstormingSubcommentCounts.set(parentId, nextIndex);
                const parentNumber = brainstormingIdeaNumbers.get(parentId);
                if (parentNumber) {
                    subcommentNumber = `${parentNumber}.${nextIndex}`;
                }
            }

            const numberCell = document.createElement("td");
            numberCell.className = "idea-col-number";
            numberCell.textContent = subcommentNumber;

            const textCell = document.createElement("td");
            textCell.className = "idea-col-text";
            const textBody = document.createElement("div");
            textBody.className = "brainstorming-idea-body";
            textBody.textContent = idea.content || idea.idea_text || "";
            textCell.appendChild(textBody);

            const authorCell = document.createElement("td");
            authorCell.className = "idea-col-author";
            renderAuthorCell(
                authorCell,
                getIdeaAuthorName(idea),
                getIdeaAuthorColor(idea),
                getIdeaAuthorAvatarPath(idea),
            );

            const timeCell = document.createElement("td");
            timeCell.className = "idea-col-time";
            timeCell.textContent = formatIdeaTimestamp(idea.timestamp);

            const menuCell = document.createElement("td");
            menuCell.className = "idea-col-menu";
            const menuButton = document.createElement("button");
            menuButton.type = "button";
            menuButton.className = "idea-menu-btn";
            menuButton.setAttribute("aria-label", "Idea options");
            menuButton.textContent = "⋮";
            menuCell.appendChild(menuButton);

            row.append(numberCell, textCell, authorCell, timeCell, menuCell);

            if (idea.parent_id) {
                const parentRow = brainstorming.ideasBody.querySelector(`[data-idea-id="${idea.parent_id}"]`);
                const replies = brainstorming.ideasBody.querySelectorAll(`[data-parent-id="${idea.parent_id}"]`);
                const anchor = replies.length ? replies[replies.length - 1] : parentRow;
                if (anchor) {
                    anchor.insertAdjacentElement("afterend", row);
                } else {
                    brainstorming.ideasBody.appendChild(row);
                }
            } else {
                brainstorming.ideasBody.appendChild(row);
            }

            if (ideaId) {
                brainstormingIdeaIds.add(ideaId);
            }
        }

        function appendIdea(idea, options = {}) {
            if (!brainstorming.ideasBody || !idea) {
                return;
            }
            const { prepend = false, subcomments = [], applyScroll = true } = options;
            const ideaId = idea.id ?? idea.idea_id;
            if (ideaId && brainstormingIdeaIds.has(ideaId)) {
                return;
            }

            // Skip subcomments in main append - they're handled separately
            if (idea.parent_id) {
                return;
            }

            if (ideaId && !brainstormingIdeaNumbers.has(ideaId)) {
                brainstormingIdeaCount += 1;
                brainstormingIdeaNumbers.set(ideaId, brainstormingIdeaCount);
                brainstormingSubcommentCounts.set(ideaId, 0);
            }

            const container = document.createElement("tr");
            container.className = "brainstorming-idea-row";
            container.dataset.ideaId = ideaId;

            const numberCell = document.createElement("td");
            numberCell.className = "idea-col-number";
            numberCell.textContent = brainstormingIdeaNumbers.get(ideaId)?.toString() || "";

            const textCell = document.createElement("td");
            textCell.className = "idea-col-text";
            const textBody = document.createElement("div");
            textBody.className = "brainstorming-idea-body";
            textBody.textContent = idea.content || idea.idea_text || "";
            textCell.appendChild(textBody);

            if (coerceConfigBool(activeBrainstormingConfig.allow_subcomments) && brainstormingActive) {
                const replyBtn = document.createElement("button");
                replyBtn.type = "button";
                replyBtn.className = "control-btn brainstorming-reply-btn";
                replyBtn.textContent = "Reply";
                replyBtn.addEventListener("click", (e) => {
                    e.stopPropagation();
                    showSubcommentForm(ideaId, container);
                });
                textCell.appendChild(replyBtn);
            }

            const authorCell = document.createElement("td");
            authorCell.className = "idea-col-author";
            renderAuthorCell(
                authorCell,
                getIdeaAuthorName(idea),
                getIdeaAuthorColor(idea),
                getIdeaAuthorAvatarPath(idea),
            );

            const timeCell = document.createElement("td");
            timeCell.className = "idea-col-time";
            timeCell.textContent = formatIdeaTimestamp(idea.timestamp);

            const menuCell = document.createElement("td");
            menuCell.className = "idea-col-menu";
            const menuButton = document.createElement("button");
            menuButton.type = "button";
            menuButton.className = "idea-menu-btn";
            menuButton.setAttribute("aria-label", "Idea options");
            menuButton.textContent = "⋮";
            menuCell.appendChild(menuButton);

            container.append(numberCell, textCell, authorCell, timeCell, menuCell);

            if (ideaId) {
                brainstormingIdeaIds.add(ideaId);
            }
            const scrollContainer = brainstorming.ideasList;
            const shouldAdjustScroll = applyScroll && Boolean(scrollContainer);
            let prevScrollTop = 0;
            let prevScrollHeight = 0;
            if (shouldAdjustScroll) {
                prevScrollTop = scrollContainer.scrollTop;
                prevScrollHeight = scrollContainer.scrollHeight;
            }

            const emptyRow = brainstorming.ideasBody.querySelector(".brainstorming-empty-row");
            if (emptyRow) {
                emptyRow.remove();
            }

            if (prepend) {
                brainstorming.ideasBody.prepend(container);
            } else {
                brainstorming.ideasBody.appendChild(container);
            }

            if (subcomments.length > 0) {
                subcomments.forEach((sub) => appendSubcomment(sub));
            }

            ensureReplyButtons();

            if (shouldAdjustScroll) {
                const autoJump = getBrainstormingAutoJumpPreference();
                if (autoJump) {
                    scrollContainer.scrollTop = scrollContainer.scrollHeight;
                } else if (prepend) {
                    const nextScrollHeight = scrollContainer.scrollHeight;
                    scrollContainer.scrollTop = prevScrollTop + (nextScrollHeight - prevScrollHeight);
                }
            }
        }

        function setBrainstormingError(message) {
            if (!brainstorming.error) {
                return;
            }
            if (!message) {
                brainstorming.error.hidden = true;
                brainstorming.error.textContent = "";
                return;
            }
            brainstorming.error.hidden = false;
            brainstorming.error.textContent = message;
        }

        function updateSubmitButtonState() {
            if (!brainstorming.submit) {
                return;
            }
            const content = (brainstorming.textarea && brainstorming.textarea.value) || "";
            const trimmed = content.trim();
            const maxLength =
                activeBrainstormingConfig.idea_character_limit || brainstormingLimits.ideaCharacterLimit;
            const ready =
                brainstormingActive &&
                !brainstormingSubmitInFlight &&
                trimmed.length > 0 &&
                (!maxLength || trimmed.length <= maxLength);
            brainstorming.submit.disabled = !ready;
        }

        function setVotingError(message) {
            if (!voting.error) {
                return;
            }
            if (!message) {
                voting.error.hidden = true;
                voting.error.textContent = "";
                return;
            }
            voting.error.hidden = false;
            voting.error.textContent = message;
        }

        function setVotingStatus(message, variant = "") {
            if (!voting.status) {
                return;
            }
            voting.status.textContent = message || "";
            if (variant) {
                voting.status.dataset.variant = variant;
            } else {
                voting.status.dataset.variant = "";
            }
        }

        function renderVotingTimingDebug() {
            if (!voting.timingDebug) {
                return;
            }
            if (!votingTiming.enabled) {
                voting.timingDebug.hidden = true;
                voting.timingDebug.textContent = "";
                return;
            }
            const snapshot = votingTiming.getState();
            if (!snapshot) {
                voting.timingDebug.hidden = false;
                voting.timingDebug.textContent = "Voting timing enabled. Waiting for next voting activation...";
                return;
            }

            const marks = snapshot.marks || {};
            const details = snapshot.details || {};
            const phase = (name) => (marks[name] !== undefined ? `${marks[name]}ms` : "--");
            const detail = (name, key, fallback = "") => {
                const value = details[name]?.[key];
                if (value === undefined || value === null || value === "") {
                    return fallback;
                }
                return String(value);
            };

            const lines = [
                `Voting Timing (${snapshot.status || "in_progress"})`,
                `activity=${snapshot.activity_id || "n/a"} trigger=${snapshot.trigger || "n/a"}`,
                `panel_visible=${phase("panel_visible")} request_start=${phase("request_start")}`,
                `response_received=${phase("response_received")} fetch=${detail("response_received", "fetch_ms", "--")}ms status=${detail("response_received", "status_code", "--")}`,
                `response_parsed=${phase("response_parsed")} is_active=${detail("response_parsed", "is_active", "--")} options=${detail("response_parsed", "options_count", "--")}`,
                `render_complete=${phase("render_complete")} render=${detail("render_complete", "render_ms", "--")}ms`,
                `interactive_ready=${phase("interactive_ready")} total=${snapshot.total_ms ?? "--"}ms`,
            ];

            voting.timingDebug.hidden = false;
            voting.timingDebug.textContent = lines.join("\n");
        }

        function setTransferStatus(message, variant = "") {
            if (!transfer.status) {
                return;
            }
            transfer.status.textContent = message || "";
            if (variant) {
                transfer.status.dataset.variant = variant;
            } else {
                transfer.status.dataset.variant = "";
            }
        }

        function setTransferError(message) {
            if (!transfer.error) {
                return;
            }
            if (!message) {
                transfer.error.hidden = true;
                transfer.error.textContent = "";
                return;
            }
            transfer.error.hidden = false;
            transfer.error.textContent = message;
        }

        function setTransferButtonsState() {
            const disabled = transferState.loading || transferState.saving || transferState.committing;
            if (transfer.includeComments) {
                transfer.includeComments.disabled = disabled;
            }
            if (transfer.targetToolType) {
                transfer.targetToolType.disabled = disabled;
            }
            if (transfer.transformProfile) {
                transfer.transformProfile.disabled = disabled;
            }
            if (transfer.addIdea) {
                transfer.addIdea.disabled = disabled;
            }
            if (transfer.saveDraft) {
                transfer.saveDraft.disabled = disabled || !transferState.dirty;
            }
            if (transfer.commit) {
                transfer.commit.disabled = disabled;
            }
        }

        function normalizeTransferItem(item) {
            return {
                id: item?.id ?? item?.source?.original_id ?? null,
                temp_id: item?.temp_id ?? (item?.id == null ? `tmp-${Date.now()}-${Math.random().toString(16).slice(2)}` : null),
                content: item?.content ?? "",
                submitted_name: item?.submitted_name ?? null,
                parent_id: item?.parent_id ?? null,
                timestamp: item?.timestamp ?? item?.created_at ?? item?.source?.created_at ?? null,
                updated_at: item?.updated_at ?? null,
                meeting_id: item?.meeting_id ?? null,
                activity_id: item?.activity_id ?? null,
                user_id: item?.user_id ?? null,
                user_color: item?.user_color ?? null,
                user_avatar_key: item?.user_avatar_key ?? null,
                user_avatar_icon_path: item?.user_avatar_icon_path ?? null,
                metadata: item?.metadata ?? {},
                source: item?.source ?? {},
            };
        }

        function buildTransferPayloadItems() {
            return transferState.items.map((item) => {
                return {
                    id: item.id,
                    content: item.content,
                    submitted_name: item.submitted_name,
                    parent_id: item.parent_id,
                    timestamp: item.timestamp,
                    updated_at: item.updated_at,
                    meeting_id: item.meeting_id,
                    activity_id: item.activity_id,
                    user_id: item.user_id,
                    user_color: item.user_color,
                    user_avatar_key: item.user_avatar_key,
                    user_avatar_icon_path: item.user_avatar_icon_path,
                    metadata: item.metadata,
                    source: item.source,
                };
            });
        }

        function buildTransferMetaBadge(label, title, variant = "") {
            const badge = document.createElement("span");
            badge.className = "transfer-meta-badge";
            badge.textContent = label;
            if (variant) {
                badge.dataset.variant = variant;
            }
            if (title) {
                badge.title = title;
            }
            return badge;
        }

        function getTransferVotingBadges(item) {
            const metadata = item?.metadata || {};
            const voting = metadata.voting || {};
            const votesRaw = voting.votes ?? metadata.votes ?? null;
            const rankRaw = voting.rank ?? metadata.rank ?? null;
            const votes = votesRaw == null ? null : coerceFiniteInt(votesRaw, null);
            const rank = rankRaw == null ? null : coerceFiniteInt(rankRaw, null);
            if (votes == null && rank == null) {
                return [];
            }
            const detailParts = [];
            if (votes != null) {
                detailParts.push(`${votes} vote${votes === 1 ? "" : "s"}`);
            }
            if (rank != null) {
                detailParts.push(`rank #${rank}`);
            }
            const title = detailParts.length ? `Voting: ${detailParts.join(" | ")}` : "";
            const badges = [];
            if (votes != null) {
                badges.push({ label: `${votes} vote${votes === 1 ? "" : "s"}`, title, variant: "voting" });
            }
            if (rank != null) {
                badges.push({ label: `#${rank}`, title, variant: "voting" });
            }
            return badges;
        }

        function formatTransferHistoryEntries(history) {
            if (!Array.isArray(history) || history.length === 0) {
                return "";
            }
            return history
                .map((entry) => {
                    if (!entry) {
                        return "";
                    }
                    const parts = [];
                    if (entry.tool_type || entry.toolType) {
                        parts.push(entry.tool_type || entry.toolType);
                    }
                    if (entry.activity_id || entry.activityId) {
                        parts.push(`activity ${entry.activity_id || entry.activityId}`);
                    }
                    if (entry.round_index != null || entry.roundIndex != null) {
                        const roundIndex = entry.round_index ?? entry.roundIndex;
                        const roundValue = Number.isFinite(Number(roundIndex))
                            ? coerceFiniteInt(roundIndex, roundIndex)
                            : roundIndex;
                        parts.push(`round ${roundValue}`);
                    }
                    if (entry.created_at || entry.createdAt) {
                        parts.push(formatTimestamp(entry.created_at || entry.createdAt));
                    }
                    return parts.length ? `- ${parts.join(" | ")}` : "";
                })
                .filter(Boolean)
                .join("\n");
        }

        function getTransferHistoryBadge(item, bundleMeta) {
            const itemHistory = item?.metadata?.history;
            const bundleHistory = bundleMeta?.history;
            const history = Array.isArray(itemHistory) && itemHistory.length
                ? itemHistory
                : Array.isArray(bundleHistory) && bundleHistory.length
                    ? bundleHistory
                    : null;
            if (history && history.length) {
                const historyText = formatTransferHistoryEntries(history);
                const title = historyText ? `History:\n${historyText}` : "";
                return { label: "History", title, variant: "history" };
            }

            const source = item?.source || bundleMeta?.source || {};
            const activityId = source.activity_id || source.activityId || null;
            const originalId = source.original_id || source.originalId || null;
            if (!activityId && !originalId) {
                return null;
            }
            const sourceLines = [];
            if (activityId) {
                sourceLines.push(`activity ${activityId}`);
            }
            if (originalId) {
                sourceLines.push(`original ${originalId}`);
            }
            const title = sourceLines.length ? `Source:\n- ${sourceLines.join("\n- ")}` : "";
            return { label: "Source", title, variant: "source" };
        }

        function getTransferBundleTooltip(bundleMeta) {
            if (!bundleMeta) {
                return "";
            }
            const historyText = formatTransferHistoryEntries(bundleMeta.history);
            const source = bundleMeta.source || {};
            const sourceLines = [];
            if (source.activity_id || source.activityId) {
                sourceLines.push(`activity ${source.activity_id || source.activityId}`);
            }
            if (source.original_id || source.originalId) {
                sourceLines.push(`original ${source.original_id || source.originalId}`);
            }
            const sections = [];
            if (historyText) {
                sections.push(`History:\n${historyText}`);
            }
            if (sourceLines.length) {
                sections.push(`Source:\n- ${sourceLines.join("\n- ")}`);
            }
            return sections.join("\n\n");
        }

        function scheduleTransferAutosave() {
            if (transferState.autosaveTimer) {
                clearTimeout(transferState.autosaveTimer);
            }
            if (!transferState.donorActivityId) {
                return;
            }
            transferState.autosaveTimer = setTimeout(() => {
                if (transferState.dirty) {
                    saveTransferDraft(true);
                }
            }, 1500);
        }

        function buildTransferTargetOptions() {
            if (!transfer.targetToolType) {
                return;
            }
            transfer.targetToolType.innerHTML = "";
            const modules = Array.isArray(state.moduleCatalog) && state.moduleCatalog.length
                ? state.moduleCatalog
                : DEFAULT_MODULES;
            const placeholder = document.createElement("option");
            placeholder.value = "";
            placeholder.textContent = "Select target activity type";
            placeholder.disabled = true;
            placeholder.selected = true;
            transfer.targetToolType.appendChild(placeholder);
            modules.forEach((module) => {
                if (!module || !module.tool_type) {
                    return;
                }
                const option = document.createElement("option");
                option.value = module.tool_type;
                option.textContent = module.label || module.tool_type;
                transfer.targetToolType.appendChild(option);
            });
        }

        function getTransferProfileOptions(toolType) {
            if (String(toolType || "").toLowerCase() === "categorization") {
                return [
                    { value: "bucket_rollup", label: "Buckets -> Rollup Ideas" },
                    { value: "bucket_suffix", label: "Ideas -> Append Category" },
                ];
            }
            return [{ value: "standard", label: "Standard Transfer" }];
        }

        function getActiveTransferProfile() {
            if (!transfer.transformProfile || transfer.transformProfile.hidden) {
                return "standard";
            }
            const selected = String(transfer.transformProfile.value || "").trim().toLowerCase();
            return selected || "standard";
        }

        function configureTransferProfileSelector(toolType, selectedProfile = null) {
            if (!transfer.transformProfile) {
                transferState.transformProfile = "standard";
                return;
            }
            const options = getTransferProfileOptions(toolType);
            transfer.transformProfile.innerHTML = "";
            options.forEach((entry) => {
                const option = document.createElement("option");
                option.value = entry.value;
                option.textContent = entry.label;
                transfer.transformProfile.appendChild(option);
            });
            const requested = String(selectedProfile || "").trim().toLowerCase();
            const values = new Set(options.map((entry) => entry.value));
            const fallback = options[0]?.value || "standard";
            const resolved = values.has(requested) ? requested : fallback;
            transfer.transformProfile.value = resolved;
            transfer.transformProfile.hidden = options.length <= 1;
            transferState.transformProfile = resolved;
        }

        function renderTransferIdeas() {
            if (!transfer.ideasBody) {
                return;
            }
            transfer.ideasBody.innerHTML = "";
            if (transfer.donorTitle) {
                transfer.donorTitle.title = getTransferBundleTooltip(transferState.metadata) || "";
            }
            const ideas = transferState.items.filter((item) => item.parent_id == null);
            const comments = transferState.items.filter((item) => item.parent_id != null);

            if (ideas.length === 0) {
                const row = document.createElement("tr");
                row.className = "brainstorming-empty-row";
                const cell = document.createElement("td");
                cell.colSpan = 5;
                cell.textContent = "No ideas available yet.";
                row.appendChild(cell);
                transfer.ideasBody.appendChild(row);
                return;
            }

            ideas.forEach((idea, ideaIndex) => {
                const row = document.createElement("tr");
                row.className = "brainstorming-idea-row";

                const numberCell = document.createElement("td");
                numberCell.className = "idea-col-number";
                numberCell.textContent = String(ideaIndex + 1);

                const textCell = document.createElement("td");
                textCell.className = "idea-col-text";
                const badgeWrap = document.createElement("div");
                badgeWrap.className = "transfer-meta-badges";
                const votingBadges = getTransferVotingBadges(idea);
                votingBadges.forEach((badge) => {
                    badgeWrap.appendChild(
                        buildTransferMetaBadge(badge.label, badge.title, badge.variant),
                    );
                });
                const historyBadge = getTransferHistoryBadge(idea, transferState.metadata);
                if (historyBadge) {
                    badgeWrap.appendChild(
                        buildTransferMetaBadge(historyBadge.label, historyBadge.title, historyBadge.variant),
                    );
                }
                if (badgeWrap.children.length) {
                    textCell.appendChild(badgeWrap);
                }
                const textarea = document.createElement("textarea");
                textarea.value = idea.content || "";
                textarea.placeholder = "Edit idea text...";
                textarea.addEventListener("input", () => {
                    idea.content = textarea.value;
                    transferState.dirty = true;
                    setTransferStatus("Unsaved changes.", "muted");
                    setTransferButtonsState();
                    scheduleTransferAutosave();
                });
                textCell.appendChild(textarea);

                const authorCell = document.createElement("td");
                authorCell.className = "idea-col-author";
                renderAuthorCell(
                    authorCell,
                    idea.submitted_name || "—",
                    idea.user_color,
                    idea.user_avatar_icon_path,
                );

                const timeCell = document.createElement("td");
                timeCell.className = "idea-col-time";
                timeCell.textContent = formatTimestamp(
                    idea.timestamp || idea.source?.created_at || idea.created_at,
                );

                const actionsCell = document.createElement("td");
                actionsCell.className = "idea-col-menu";
                const actionWrap = document.createElement("div");
                actionWrap.className = "transfer-row-actions";
                const upBtn = document.createElement("button");
                upBtn.type = "button";
                upBtn.className = "control-btn sm";
                upBtn.textContent = "↑";
                upBtn.disabled = ideaIndex === 0;
                upBtn.addEventListener("click", () => moveTransferIdea(ideaIndex, -1));
                const downBtn = document.createElement("button");
                downBtn.type = "button";
                downBtn.className = "control-btn sm";
                downBtn.textContent = "↓";
                downBtn.disabled = ideaIndex === ideas.length - 1;
                downBtn.addEventListener("click", () => moveTransferIdea(ideaIndex, 1));
                const deleteBtn = document.createElement("button");
                deleteBtn.type = "button";
                deleteBtn.className = "control-btn sm destructive";
                deleteBtn.textContent = "✖";
                deleteBtn.addEventListener("click", () => removeTransferIdea(idea));
                actionWrap.append(upBtn, downBtn, deleteBtn);
                actionsCell.appendChild(actionWrap);

                row.append(numberCell, textCell, authorCell, timeCell, actionsCell);
                transfer.ideasBody.appendChild(row);

                if (transferState.includeComments) {
                    const ideaKey = idea.id ?? idea.temp_id;
                    const related = comments.filter((comment) => String(comment.parent_id) === String(ideaKey));
                    related.forEach((comment) => {
                        const commentRow = document.createElement("tr");
                        commentRow.className = "brainstorming-subcomment-row transfer-comment-row";
                        const commentNumber = document.createElement("td");
                        commentNumber.className = "idea-col-number";
                        commentNumber.textContent = "↳";
                        const commentTextCell = document.createElement("td");
                        commentTextCell.className = "idea-col-text";
                        const commentText = document.createElement("textarea");
                        commentText.value = comment.content || "";
                        commentText.placeholder = "Edit comment…";
                        commentText.addEventListener("input", () => {
                            comment.content = commentText.value;
                            transferState.dirty = true;
                            setTransferStatus("Unsaved changes.", "muted");
                            setTransferButtonsState();
                            scheduleTransferAutosave();
                        });
                        commentTextCell.appendChild(commentText);
                        const commentAuthor = document.createElement("td");
                        commentAuthor.className = "idea-col-author";
                        renderAuthorCell(
                            commentAuthor,
                            comment.submitted_name || "—",
                            comment.user_color,
                            comment.user_avatar_icon_path,
                        );
                        const commentTime = document.createElement("td");
                        commentTime.className = "idea-col-time";
                        commentTime.textContent = formatTimestamp(
                            comment.timestamp || comment.source?.created_at || comment.created_at,
                        );
                        const commentActions = document.createElement("td");
                        commentActions.className = "idea-col-menu";
                        const deleteComment = document.createElement("button");
                        deleteComment.type = "button";
                        deleteComment.className = "control-btn sm destructive";
                        deleteComment.textContent = "✖";
                        deleteComment.addEventListener("click", () => removeTransferComment(comment));
                        commentActions.appendChild(deleteComment);
                        commentRow.append(
                            commentNumber,
                            commentTextCell,
                            commentAuthor,
                            commentTime,
                            commentActions,
                        );
                        transfer.ideasBody.appendChild(commentRow);
                    });
                }
            });
        }

        function moveTransferIdea(index, delta) {
            const ideas = transferState.items.filter((item) => item.parent_id == null);
            const targetIndex = index + delta;
            if (targetIndex < 0 || targetIndex >= ideas.length) {
                return;
            }
            const ideaToMove = ideas[index];
            const ideaIdsInOrder = ideas.map((idea) => idea.id ?? idea.temp_id);
            ideaIdsInOrder.splice(index, 1);
            ideaIdsInOrder.splice(targetIndex, 0, ideaToMove.id ?? ideaToMove.temp_id);

            const reordered = [];
            ideaIdsInOrder.forEach((ideaId) => {
                const idea = transferState.items.find(
                    (item) => (item.id ?? item.temp_id) === ideaId && item.parent_id == null,
                );
                if (idea) {
                    reordered.push(idea);
                    transferState.items
                        .filter((item) => item.parent_id != null && String(item.parent_id) === String(ideaId))
                        .forEach((comment) => reordered.push(comment));
                }
            });

            const ungrouped = transferState.items.filter(
                (item) => item.parent_id != null && !ideaIdsInOrder.includes(item.parent_id),
            );
            transferState.items = [...reordered, ...ungrouped];
            transferState.dirty = true;
            setTransferStatus("Unsaved changes.", "muted");
            setTransferButtonsState();
            renderTransferIdeas();
            scheduleTransferAutosave();
        }

        function removeTransferIdea(idea) {
            const key = idea.id ?? idea.temp_id;
            transferState.items = transferState.items.filter(
                (item) => item !== idea && String(item.parent_id) !== String(key),
            );
            transferState.dirty = true;
            setTransferStatus("Unsaved changes.", "muted");
            setTransferButtonsState();
            renderTransferIdeas();
            scheduleTransferAutosave();
        }

        function removeTransferComment(comment) {
            transferState.items = transferState.items.filter((item) => item !== comment);
            transferState.dirty = true;
            setTransferStatus("Unsaved changes.", "muted");
            setTransferButtonsState();
            renderTransferIdeas();
            scheduleTransferAutosave();
        }

        function addTransferIdea() {
            const newIdea = normalizeTransferItem({
                content: "",
                parent_id: null,
            });
            if (!newIdea.temp_id) {
                newIdea.temp_id = `idea-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            }
            transferState.items.push(newIdea);
            transferState.dirty = true;
            setTransferStatus("Unsaved changes.", "muted");
            setTransferButtonsState();
            renderTransferIdeas();
        }

        function resetTransferState() {
            transferState.donorActivityId = null;
            transferState.donorOrderIndex = null;
            transferState.donorToolType = null;
            transferState.transformProfile = "standard";
            transferState.items = [];
            transferState.metadata = {};
            transferState.dirty = false;
            transferState.loading = false;
            transferState.saving = false;
            transferState.committing = false;
            transferState.loadAttempted = false;
            transferState.loadSucceeded = false;
            if (transferState.autosaveTimer) {
                clearTimeout(transferState.autosaveTimer);
                transferState.autosaveTimer = null;
            }
            if (transfer.includeComments) {
                transfer.includeComments.checked = true;
            }
            configureTransferProfileSelector(null, "standard");
            if (transfer.donorTitle) {
                transfer.donorTitle.textContent = "Select a brainstorming activity";
            }
            if (transfer.ideasBody) {
                transfer.ideasBody.innerHTML = "";
            }
            setTransferStatus("");
            setTransferError("");
            setTransferButtonsState();
        }

        async function openTransferModal(activity) {
            if (!transfer.root || !activity) {
                return;
            }
            resetTransferState();
            transferState.donorActivityId = activity.activity_id || activity.activityId || activity.id || null;
            transferState.donorOrderIndex = activity.order_index || null;
            transferState.donorToolType = String(activity.tool_type || activity.toolType || "").toLowerCase();
            configureTransferProfileSelector(transferState.donorToolType, null);
            if (transfer.donorTitle) {
                transfer.donorTitle.textContent = activity.title || "Selected activity";
            }
            if (transfer.includeComments) {
                transferState.includeComments = transfer.includeComments.checked;
            }
            transferState.active = true;
            transfer.root.hidden = false;
            if (!transferState.donorActivityId) {
                setTransferError("Unable to identify the activity to transfer from.");
                setTransferStatus("", "");
                return;
            }
            setTransferStatus(`Opening transfer for ${transferState.donorActivityId}...`, "info");
            console.info("transfer open", { activityId: transferState.donorActivityId });
            await loadTransferBundles();
            try {
                updateActivityPanels(state.latestState);
            } catch (error) {
                console.error("Transfer panel update failed:", error);
            }
        }

        function closeTransferModal() {
            if (transfer.root) {
                transfer.root.hidden = true;
            }
            transferState.active = false;
            resetTransferState();
            updateActivityPanels(state.latestState);
        }

        async function loadTransferBundles() {
            if (!transferState.donorActivityId) {
                setTransferError("No activity selected for transfer.");
                return;
            }
            transferState.loading = true;
            transferState.loadAttempted = true;
            setTransferButtonsState();
            setTransferError("");
            setTransferStatus("Loading transfer bundle...", "info");
            try {
                const params = new URLSearchParams({
                    activity_id: transferState.donorActivityId,
                    include_comments: String(transfer.includeComments?.checked ?? true),
                    transfer_profile: getActiveTransferProfile(),
                });
                const transferUrl = `/api/meetings/${encodeURIComponent(context.meetingId)}/transfer/bundles?${params.toString()}`;
                setTransferStatus(`Requesting transfer bundle for ${transferState.donorActivityId}...`, "info");
                const response = await fetch(
                    transferUrl,
                    { credentials: "include" },
                );
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || `Unable to load transfer bundle (${response.status}).`);
                }
                console.info("transfer bundles loaded", { transferUrl, draft: data.draft, input: data.input });
                const draftItems = Array.isArray(data.draft?.items) ? data.draft.items : null;
                const inputItems = Array.isArray(data.input?.items) ? data.input.items : null;
                const selectedProfile = getActiveTransferProfile();
                const draftProfile = String(data.draft?.metadata?.transfer_profile || "").toLowerCase();
                const useDraft =
                    Boolean(draftItems && draftItems.length > 0) &&
                    (!selectedProfile || draftProfile === selectedProfile);
                const bundle = useDraft ? data.draft : (data.input || data.draft || {});
                transferState.items = Array.isArray(bundle.items)
                    ? bundle.items.map((item) => normalizeTransferItem(item))
                    : [];
                if (!transferState.items.length) {
                    const ideasUrl = `/api/meetings/${encodeURIComponent(context.meetingId)}/brainstorming/ideas?activity_id=${encodeURIComponent(transferState.donorActivityId)}`;
                    const ideaResponse = await fetch(
                        ideasUrl,
                        { credentials: "include" },
                    );
                    const ideaData = await ideaResponse.json().catch(() => ([]));
                    if (ideaResponse.ok && Array.isArray(ideaData)) {
                        transferState.items = ideaData.map((idea) => normalizeTransferItem({
                            id: idea.id,
                            content: idea.content,
                            submitted_name: idea.submitted_name,
                            parent_id: idea.parent_id,
                            timestamp: idea.timestamp || idea.created_at,
                            user_id: idea.user_id,
                            user_color: idea.user_color,
                            user_avatar_key: idea.user_avatar_key,
                            user_avatar_icon_path: idea.user_avatar_icon_path,
                            metadata: idea.metadata || {},
                            source: {
                                original_id: idea.id,
                                created_at: idea.created_at || idea.timestamp,
                            },
                        }));
                        console.info("transfer fallback ideas loaded", { ideasUrl, count: transferState.items.length });
                    } else {
                        console.warn("transfer fallback ideas failed", { ideasUrl, status: ideaResponse.status, ideaData });
                    }
                }
                transferState.items.forEach((item) => {
                    if (item.parent_id == null) {
                        item.temp_id = item.temp_id || item.id || item.source?.original_id || `idea-${Math.random().toString(16).slice(2)}`;
                    }
                });
                transferState.items.forEach((item) => {
                    if (item.parent_id != null) {
                        const parentId = item.parent_id;
                        const parent = transferState.items.find(
                            (idea) => idea.parent_id == null && String(idea.id ?? idea.temp_id) === String(parentId),
                        );
                        if (!parent) {
                            item.parent_id = null;
                        }
                    }
                });
                transferState.metadata = bundle.metadata || {};
                const resolvedProfile = String(transferState.metadata.transfer_profile || getActiveTransferProfile()).toLowerCase();
                transferState.transformProfile = resolvedProfile || "standard";
                configureTransferProfileSelector(transferState.donorToolType, transferState.transformProfile);
                transferState.dirty = false;
                transferState.loadSucceeded = true;
                const loadedCount = transferState.items.length;
                const summary = useDraft ? "Draft loaded." : "Input bundle loaded.";
                setTransferStatus(
                    loadedCount ? `${summary} (${loadedCount} items)` : "No ideas found for this activity.",
                    loadedCount ? "success" : "info",
                );
                renderTransferIdeas();
            } catch (error) {
                console.error("Transfer load failed:", error);
                setTransferError(error.message || "Unable to load transfer bundle.");
                setTransferStatus("", "");
            } finally {
                transferState.loading = false;
                setTransferButtonsState();
            }
        }

        async function saveTransferDraft(silent = false) {
            if (!transferState.donorActivityId || transferState.saving) {
                return;
            }
            transferState.saving = true;
            setTransferButtonsState();
            if (!silent) {
                setTransferStatus("Saving draft...", "info");
            }
            try {
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/transfer/draft?activity_id=${encodeURIComponent(transferState.donorActivityId)}`,
                    {
                        method: "PUT",
                        credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            include_comments: transfer.includeComments?.checked ?? true,
                            items: buildTransferPayloadItems(),
                            metadata: transferState.metadata,
                        }),
                    },
                );
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || "Unable to save draft.");
                }
                transferState.items = Array.isArray(data.items)
                    ? data.items.map((item) => normalizeTransferItem(item))
                    : transferState.items;
                transferState.metadata = data.metadata || transferState.metadata;
                transferState.dirty = false;
                renderTransferIdeas();
                setTransferStatus("Draft saved.", "success");
            } catch (error) {
                console.error("Transfer save failed:", error);
                setTransferError(error.message || "Unable to save draft.");
                if (!silent) {
                    setTransferStatus("Draft not saved.", "error");
                }
            } finally {
                transferState.saving = false;
                setTransferButtonsState();
            }
        }

        async function commitTransfer() {
            if (!transferState.donorActivityId || transferState.committing) {
                return;
            }
            transferState.committing = true;
            setTransferButtonsState();
            setTransferError("");
            setTransferStatus("Creating next activity...", "info");
            try {
                const targetTool = transfer.targetToolType?.value;
                if (!targetTool) {
                    throw new Error("Select a next activity type.");
                }
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/transfer/commit`,
                    {
                        method: "POST",
                        credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                            donor_activity_id: transferState.donorActivityId,
                            include_comments: transfer.includeComments?.checked ?? true,
                            items: buildTransferPayloadItems(),
                            metadata: transferState.metadata,
                            target_activity: {
                                tool_type: targetTool,
                            },
                        }),
                    },
                );
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data.detail || "Unable to create next activity.");
                }
                if (Array.isArray(data.agenda)) {
                    renderAgenda(data.agenda);
                }
                const newActivity = data.new_activity || null;
                if (newActivity?.activity_id) {
                    selectAgendaItem(newActivity.activity_id, { source: "user" });
                    localStorage.setItem(
                        `transfer:lastActivity:${context.meetingId}`,
                        newActivity.activity_id,
                    );
                }
                setTransferStatus("Next activity created.", "success");
                closeTransferModal();
                const settingsUrl = `/meeting/${encodeURIComponent(context.meetingId)}/settings`;
                if (newActivity?.activity_id) {
                    window.location.href = `${settingsUrl}?activity_id=${encodeURIComponent(newActivity.activity_id)}`;
                } else {
                    window.location.href = settingsUrl;
                }
            } catch (error) {
                console.error("Transfer commit failed:", error);
                setTransferError(error.message || "Unable to create next activity.");
                setTransferStatus("Transfer failed.", "error");
            } finally {
                transferState.committing = false;
                setTransferButtonsState();
            }
        }

        function coerceFiniteInt(value, fallback = 0) {
            const parsed = Number(value);
            return Number.isFinite(parsed) ? Math.trunc(parsed) : fallback;
        }

        function syncVotingDraftFromSummary(summary, { force = false } = {}) {
            if (!summary) {
                votingDraftActivityId = null;
                votingDraftDirty = false;
                votingDraftSignature = null;
                votingDraftVotes = new Map();
                votingCommittedVotes = new Map();
                return;
            }

            const activityId = summary.activity_id || null;
            const activityChanged =
                Boolean(activityId && votingDraftActivityId && activityId !== votingDraftActivityId);
            const signature = Array.isArray(summary.options)
                ? summary.options.map((option) => option.option_id).join("|")
                : "";
            const signatureChanged = signature !== votingDraftSignature;
            if (!force && votingDraftDirty && !activityChanged && !signatureChanged) {
                return;
            }

            votingDraftActivityId = activityId;
            votingDraftSignature = signature;
            votingCommittedVotes = new Map(
                (summary.options || []).map((option) => [
                    option.option_id,
                    coerceFiniteInt(option.user_votes, 0),
                ]),
            );
            votingDraftVotes = new Map(votingCommittedVotes);
            votingDraftDirty = false;
        }

        function getVotingDraftTotal() {
            let total = 0;
            votingDraftVotes.forEach((count) => {
                total += Math.max(0, coerceFiniteInt(count, 0));
            });
            return total;
        }

        function isVotingEffectivelyActive(summary) {
            if (summary?.is_active === true) {
                return true;
            }
            if (votingIsActive) {
                return true;
            }

            const activityId =
                summary?.activity_id || votingActivityId || state.selectedActivityId || state.latestState?.currentActivity;
            if (!activityId) {
                return false;
            }

            const activeEntry = state.activeActivities?.[activityId];
            const activeStatus = String(activeEntry?.status || "").toLowerCase();
            if (activeStatus === "in_progress" || activeStatus === "paused") {
                return true;
            }

            if (state.latestState?.currentActivity === activityId) {
                const status = String(state.latestState?.status || "").toLowerCase();
                if (status === "in_progress" || status === "paused") {
                    return true;
                }
            }
            return false;
        }

        function updateVotingFooter(summary) {
            if (!voting.footer || !voting.progress || !voting.submit || !voting.reset) {
                return;
            }
            const hasSummary = Boolean(summary && summary.activity_id);
            voting.footer.hidden = !hasSummary;
            if (!hasSummary) {
                voting.progress.textContent = "";
                voting.submit.disabled = true;
                voting.reset.disabled = true;
                setVotingStatus("");
                if (voting.remaining) {
                    voting.remaining.textContent = "0";
                }
                // Hide View Results button when voting is not active
                if (voting.viewResultsButton) {
                    voting.viewResultsButton.hidden = true;
                }
                return;
            }

            const maxVotes = Math.max(0, coerceFiniteInt(summary.max_votes, 0));
            const cast = getVotingDraftTotal();
            const remaining = Math.max(0, maxVotes - cast);

            if (voting.remaining) {
                voting.remaining.textContent = String(remaining);
            }

            const nounSingular = summary.vote_label_singular || "pick";
            const nounPlural = summary.vote_label_plural || "picks";
            const noun = cast === 1 ? nounSingular : nounPlural;
            voting.progress.textContent =
                maxVotes > 0
                    ? `You've cast ${cast} of your ${maxVotes} ${noun}.`
                    : `You've cast ${cast} ${noun}.`;

            const canSubmit = isVotingEffectivelyActive(summary) && !votingRequestInFlight;
            voting.submit.disabled = !canSubmit || !votingDraftDirty || (maxVotes > 0 && cast > maxVotes);
            voting.reset.disabled = !votingDraftDirty || votingRequestInFlight;

            // Show/hide View Results button based on active state plus visibility policy.
            if (voting.viewResultsButton) {
                const isActiveState = isVotingEffectivelyActive(summary);
                const isPrivilegedViewer = Boolean(state.isFacilitator || isAdminUser);
                const canViewResults =
                    summary.can_view_results !== undefined
                        ? Boolean(summary.can_view_results)
                        : state.isFacilitator || isAdminUser || Boolean(summary.show_results);
                voting.viewResultsButton.hidden = !(isPrivilegedViewer || (isActiveState && canViewResults));
            }
        }

        function adjustVotingDraft(optionId, delta, summary) {
            if (!summary || !optionId || votingRequestInFlight || !isVotingEffectivelyActive(summary)) {
                return;
            }
            const maxVotes = Math.max(0, coerceFiniteInt(summary.max_votes, 0));
            const perOptionCap =
                summary.max_votes_per_option !== null && summary.max_votes_per_option !== undefined
                    ? coerceFiniteInt(summary.max_votes_per_option, 0)
                    : null;
            const allowRetract = Boolean(summary.allow_retract);

            const baseline = coerceFiniteInt(votingCommittedVotes.get(optionId), 0);
            const current = coerceFiniteInt(votingDraftVotes.get(optionId), baseline);
            const draftTotal = getVotingDraftTotal();

            if (delta > 0) {
                if (maxVotes && draftTotal >= maxVotes) {
                    return;
                }
                if (perOptionCap && current >= perOptionCap) {
                    return;
                }
                votingDraftVotes.set(optionId, current + 1);
                votingDraftDirty = true;
                setVotingError(null);
                setVotingStatus("");
                renderVotingSummary(summary);
                return;
            }

            if (delta < 0) {
                const minAllowed = allowRetract ? 0 : baseline;
                if (current <= minAllowed) {
                    return;
                }
                votingDraftVotes.set(optionId, current - 1);
                votingDraftDirty = true;
                setVotingError(null);
                setVotingStatus("");
                renderVotingSummary(summary);
            }
        }

        function applyVotingDraftCount(optionId, desired, summary, committedCount, draftCount) {
            if (!summary || !optionId || votingRequestInFlight || !votingIsActive) {
                return;
            }
            const maxVotes = Math.max(0, coerceFiniteInt(summary.max_votes, 0));
            const perOptionCap =
                summary.max_votes_per_option !== null && summary.max_votes_per_option !== undefined
                    ? coerceFiniteInt(summary.max_votes_per_option, 0)
                    : null;
            const allowRetract = Boolean(summary.allow_retract);
            const baseline = coerceFiniteInt(committedCount, 0);
            const minAllowed = allowRetract ? 0 : baseline;
            const currentTotalWithout = getVotingDraftTotal() - Math.max(0, draftCount);
            let next = Math.max(coerceFiniteInt(desired, 0), minAllowed);

            if (perOptionCap && Number.isFinite(perOptionCap)) {
                next = Math.min(next, Math.floor(perOptionCap));
            }
            if (maxVotes && currentTotalWithout + next > maxVotes) {
                next = Math.max(minAllowed, maxVotes - currentTotalWithout);
                setVotingError("Pick limit reached for this activity.");
            } else {
                setVotingError(null);
            }

            if (next === draftCount) {
                return;
            }

            votingDraftVotes.set(optionId, next);
            votingDraftDirty = true;
            setVotingStatus("");
            renderVotingSummary(summary);
        }

        function handleVotingDotClick(event) {
            const target = event.target instanceof Element ? event.target.closest(".voting-dot") : null;
            if (!(target instanceof HTMLButtonElement) || target.disabled) {
                return;
            }
            const summary = votingSummary;
            if (!summary || !votingIsActive || votingRequestInFlight) {
                return;
            }
            const optionId = String(target.dataset.optionId || "").trim();
            if (!optionId) {
                return;
            }
            const desired = Math.max(0, coerceFiniteInt(target.dataset.value, 0));
            if (!desired) {
                return;
            }
            const committedCount = coerceFiniteInt(votingCommittedVotes.get(optionId), 0);
            const draftCount = coerceFiniteInt(votingDraftVotes.get(optionId), committedCount);
            applyVotingDraftCount(optionId, desired, summary, committedCount, draftCount);
        }

        function resetVotingDraft(summary) {
            if (!summary || votingRequestInFlight) {
                return;
            }
            votingDraftVotes = new Map(votingCommittedVotes);
            votingDraftDirty = false;
            setVotingError(null);
            setVotingStatus("Draft reset.", "success");
            renderVotingSummary(summary);
        }

        async function postVote(optionId, action = "add") {
            const response = await runReliableWriteAction({
                toolType: "voting",
                actionName: "cast_vote",
                queueName: "voting-submit",
                requestFactory: ({ attempt, requestId, policy }) => fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/voting/votes`,
                    {
                        method: "POST",
                        credentials: "include",
                        headers: {
                            "Content-Type": "application/json",
                            [policy.idempotencyHeader]: requestId || "",
                            "X-Retry-Attempt": String(attempt),
                        },
                        body: JSON.stringify({
                            activity_id: votingActivityId,
                            option_id: optionId,
                            action,
                        }),
                    },
                ),
                onRetry: ({ attempt }) => {
                    setVotingStatus(`Connection busy. Retrying vote (${attempt + 1})…`);
                },
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to submit vote.");
            }
            return response.json();
        }

        async function submitVotingDraft() {
            const summary = votingSummary;
            if (!summary || !votingDraftDirty || votingRequestInFlight || !isVotingEffectivelyActive(summary)) {
                return;
            }

            const maxVotes = Math.max(0, coerceFiniteInt(summary.max_votes, 0));
            const cast = getVotingDraftTotal();
            if (maxVotes && cast > maxVotes) {
                setVotingError("You have selected more picks than allowed.");
                return;
            }

            const allowRetract = Boolean(summary.allow_retract);
            const operations = [];
            for (const option of summary.options || []) {
                const optionId = option.option_id;
                const baseline = coerceFiniteInt(votingCommittedVotes.get(optionId), 0);
                const desired = coerceFiniteInt(votingDraftVotes.get(optionId), baseline);
                const delta = desired - baseline;
                if (delta > 0) {
                    for (let i = 0; i < delta; i += 1) {
                        operations.push({ optionId, action: "add" });
                    }
                } else if (delta < 0) {
                    if (!allowRetract) {
                        setVotingError("This voting activity does not allow retraction.");
                        return;
                    }
                    for (let i = 0; i < Math.abs(delta); i += 1) {
                        operations.push({ optionId, action: "retract" });
                    }
                }
            }

            if (operations.length === 0) {
                votingDraftDirty = false;
                updateVotingFooter(summary);
                return;
            }

            votingRequestInFlight = true;
            setVotingError(null);
            setVotingStatus("Submitting picks...", "");
            updateVotingFooter(summary);

            let latest = null;
            try {
                for (const op of operations) {
                    latest = await postVote(op.optionId, op.action);
                }
                setVotingStatus("Submitted.", "success");
                setVotingError(null);
                syncVotingDraftFromSummary(latest, { force: true });
            } catch (error) {
                setVotingError(error.message || "Unable to submit picks.");
                setVotingStatus("Submission failed.", "error");
            } finally {
                votingRequestInFlight = false;
                renderVotingSummary(latest || summary);
            }
        }

        function openVotingResultsModal() {
            if (!voting.resultsModal || !voting.resultsBody || !votingSummary) {
                return;
            }
            populateVotingResultsTable();
            voting.resultsModal.hidden = false;
        }

        function closeVotingResultsModal() {
            if (!voting.resultsModal) {
                return;
            }
            voting.resultsModal.hidden = true;
        }

        function populateVotingResultsTable() {
            if (!voting.resultsBody || !votingSummary || !votingSummary.options) {
                return;
            }
            const canViewResults = Boolean(votingSummary.can_view_results);

            // Sort options by votes descending (no secondary sort)
            const sortedOptions = [...votingSummary.options].sort((a, b) => {
                const votesA = a.votes ?? 0;
                const votesB = b.votes ?? 0;
                return votesB - votesA;
            });

            // Clear existing rows
            voting.resultsBody.innerHTML = "";
            if (!canViewResults) {
                const emptyRow = document.createElement("tr");
                const emptyCell = document.createElement("td");
                emptyCell.colSpan = 2;
                emptyCell.textContent = "Results are hidden until you submit your vote.";
                emptyRow.appendChild(emptyCell);
                voting.resultsBody.appendChild(emptyRow);
                return;
            }

            if (sortedOptions.length === 0) {
                const emptyRow = document.createElement("tr");
                const emptyCell = document.createElement("td");
                emptyCell.colSpan = 2;
                emptyCell.textContent = "No results available.";
                emptyRow.appendChild(emptyCell);
                voting.resultsBody.appendChild(emptyRow);
                return;
            }

            // Populate table with sorted results
            sortedOptions.forEach((option) => {
                const row = document.createElement("tr");

                const votesCell = document.createElement("td");
                votesCell.className = "votes-col";
                votesCell.textContent = String(option.votes ?? 0);

                const ideaCell = document.createElement("td");
                ideaCell.className = "idea-col";
                ideaCell.textContent = option.label || "";

                row.appendChild(votesCell);
                row.appendChild(ideaCell);
                voting.resultsBody.appendChild(row);
            });
        }

        function renderVotingSummary(summary) {
            const renderStartedAt =
                votingTiming.enabled && window.performance && typeof window.performance.now === "function"
                    ? window.performance.now()
                    : 0;
            votingSummary = summary;
            votingActivityId = summary?.activity_id || null;

            syncVotingDraftFromSummary(summary);
            if (voting.notice) {
                if (!summary) {
                    voting.notice.textContent = "";
                } else if (summary.show_results) {
                    voting.notice.textContent = "Results update live as votes are recorded.";
                } else if (summary.can_view_results) {
                    voting.notice.textContent = "You can view current results from the results button.";
                } else {
                    voting.notice.textContent = "Votes are hidden until the facilitator reveals the results.";
                }
            }

            if (!voting.list) {
                return;
            }
            if (!summary) {
                updateVotingFooter(null);
                const empty = document.createElement("li");
                empty.className = "voting-option voting-option-empty";
                empty.textContent = "Voting is not active.";
                voting.list.replaceChildren(empty);
                return;
            }

            if (!summary.options || summary.options.length === 0) {
                updateVotingFooter(summary);
                const empty = document.createElement("li");
                empty.className = "voting-option voting-option-empty";
                const message = document.createElement("div");
                message.textContent = "No options yet. Add choices before starting voting.";
                empty.appendChild(message);
                if (state.isFacilitator) {
                    const editBtn = document.createElement("button");
                    editBtn.type = "button";
                    editBtn.className = "control-btn sm";
                    editBtn.textContent = "Edit options";
                    editBtn.addEventListener("click", () => {
                        const settingsUrl = `/meeting/${encodeURIComponent(context.meetingId)}/settings`;
                        if (summary.activity_id) {
                            window.location.href = `${settingsUrl}?activity_id=${encodeURIComponent(summary.activity_id)}`;
                        } else {
                            window.location.href = settingsUrl;
                        }
                    });
                    empty.appendChild(editBtn);
                }
                voting.list.replaceChildren(empty);
                return;
            }

            const fragment = document.createDocumentFragment();
            const draftTotal = getVotingDraftTotal();
            summary.options.forEach((option) => {
                const draftCount = coerceFiniteInt(
                    votingDraftVotes.get(option.option_id),
                    coerceFiniteInt(option.user_votes, 0),
                );
                const committedCount = coerceFiniteInt(
                    votingCommittedVotes.get(option.option_id),
                    coerceFiniteInt(option.user_votes, 0),
                );

                const li = document.createElement("li");
                li.className = "voting-option";
                li.dataset.dirty = String(votingDraftDirty && draftCount !== committedCount);
                const main = document.createElement("div");
                main.className = "voting-option-main";
                const header = document.createElement("div");
                header.className = "voting-option-header";
                const label = document.createElement("div");
                label.className = "voting-option-label";
                label.textContent = option.label;
                const meta = document.createElement("div");
                meta.className = "voting-option-meta";
                const labelPlural = summary.vote_label_plural || "votes";

                if (summary.can_view_results && option.votes !== null && option.votes !== undefined) {
                    const voteCount = document.createElement("span");
                    voteCount.className = "voting-option-count";
                    const hotThreshold = Math.max(1, Math.ceil(summary.options.length / 2));
                    if (option.votes >= hotThreshold) {
                        voteCount.dataset.variant = "hot";
                    } else if (option.votes > 0) {
                        voteCount.dataset.variant = "warm";
                    }
                    voteCount.textContent = `${option.votes} ${labelPlural}`;
                    meta.appendChild(voteCount);
                }

                if (draftCount > 0) {
                    const tag = document.createElement("span");
                    tag.className = "voting-option-tag";
                    tag.textContent = draftCount === 1 ? "1 selected" : `${draftCount} selected`;
                    meta.appendChild(tag);
                }

                const perOptionCap =
                    summary.max_votes_per_option !== null && summary.max_votes_per_option !== undefined
                        ? Number(summary.max_votes_per_option)
                        : null;
                const maxVotes = Math.max(0, coerceFiniteInt(summary.max_votes, 0));

                let selectCap = 1;
                if (perOptionCap && Number.isFinite(perOptionCap)) {
                    selectCap = Math.max(1, Math.floor(perOptionCap));
                } else if (maxVotes) {
                    selectCap = Math.max(1, Math.floor(maxVotes));
                }
                const maxDotsPerOption = 9;
                selectCap = Math.min(selectCap, maxDotsPerOption);
                if (maxVotes) {
                    selectCap = Math.min(selectCap, maxVotes);
                }

                const allowRetract = Boolean(summary.allow_retract);
                const minAllowed = allowRetract ? 0 : committedCount;
                const currentTotalWithout = draftTotal - Math.max(0, draftCount);
                const isEffectiveActive = isVotingEffectivelyActive(summary);
                const rail = document.createElement("div");
                rail.className = "voting-dot-rail";
                rail.setAttribute("role", "radiogroup");
                rail.setAttribute("aria-label", `Pick count for ${option.label}`);

                const voteLabelSingular = summary.vote_label_singular || "pick";
                const voteLabelPlural = summary.vote_label_plural || "picks";
                for (let i = 1; i <= selectCap; i += 1) {
                    const dot = document.createElement("button");
                    dot.type = "button";
                    dot.className = "voting-dot";
                    dot.dataset.index = String(i);
                    dot.dataset.active = String(i <= draftCount);
                    dot.dataset.optionId = option.option_id;
                    dot.dataset.value = String(i);
                    dot.setAttribute(
                        "aria-label",
                        `Set ${option.label} to ${i} ${i === 1 ? voteLabelSingular : voteLabelPlural}`,
                    );

                    const exceedsTotal = maxVotes && currentTotalWithout + i > maxVotes;
                    dot.disabled =
                        votingRequestInFlight ||
                        !isEffectiveActive ||
                        (!allowRetract && i < minAllowed) ||
                        (perOptionCap && Number.isFinite(perOptionCap) && i > perOptionCap) ||
                        (exceedsTotal && i > draftCount);
                    rail.appendChild(dot);
                }

                header.append(rail, label);
                main.append(header, meta);
                li.append(main);
                fragment.appendChild(li);
            });
            voting.list.replaceChildren(fragment);
            if (votingTiming.enabled && renderStartedAt > 0) {
                votingTiming.mark("render_complete", {
                    options_count: summary.options.length,
                    render_ms: Math.round(window.performance.now() - renderStartedAt),
                });
            }
            if (summary?.is_active === false && isVotingEffectivelyActive(summary)) {
                votingTiming.mark("active_state_override", {
                    summary_is_active: false,
                    effective_is_active: true,
                    activity_id: summary?.activity_id || null,
                });
            }
            const firstEnabledDot = voting.list.querySelector(".voting-dot:not(:disabled)");
            if (firstEnabledDot) {
                votingTiming.mark("interactive_ready", {
                    options_count: summary.options.length,
                    is_active: Boolean(summary?.is_active),
                    effective_is_active: isVotingEffectivelyActive(summary),
                });
                votingTiming.end("interactive");
            } else if (summary && summary.options && summary.options.length > 0) {
                votingTiming.mark("rendered_without_enabled_dots", {
                    options_count: summary.options.length,
                    is_active: Boolean(summary?.is_active),
                    effective_is_active: isVotingEffectivelyActive(summary),
                    request_in_flight: Boolean(votingRequestInFlight),
                });
            }

            updateVotingFooter(summary);
            if (voting.resultsModal && !voting.resultsModal.hidden) {
                populateVotingResultsTable();
            }
        }

        async function loadVotingOptions(activityId, config = {}) {
            if (!voting.root || !activityId) {
                return;
            }
            votingTiming.begin(activityId, "load_options");
            if (votingOptionsRefreshInFlight) {
                votingTiming.mark("load_skipped_inflight");
                return;
            }
            votingOptionsRefreshInFlight = true;
            const fetchStartedAt =
                votingTiming.enabled && window.performance && typeof window.performance.now === "function"
                    ? window.performance.now()
                    : 0;
            try {
                votingTiming.mark("request_start");
                const requestHeaders = votingTiming.enabled
                    ? { "X-Debug-Voting-Timing": "1" }
                    : undefined;
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/voting/options?activity_id=${encodeURIComponent(activityId)}`,
                    { credentials: "include", headers: requestHeaders },
                );
                if (votingTiming.enabled && fetchStartedAt > 0) {
                    votingTiming.mark("response_received", {
                        status_code: response.status,
                        fetch_ms: Math.round(window.performance.now() - fetchStartedAt),
                    });
                }
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    votingTiming.end("request_error", {
                        status_code: response.status,
                        detail: err.detail || "Unable to load voting options.",
                    });
                    throw new Error(err.detail || "Unable to load voting options.");
                }
                const summary = await response.json();
                votingTiming.mark("response_parsed", {
                    options_count: Array.isArray(summary?.options) ? summary.options.length : 0,
                    is_active: Boolean(summary?.is_active),
                });

                // Apply config overrides if present
                if (config.max_votes !== undefined) {
                    summary.max_votes = config.max_votes; // Store max_votes for reference if needed
                    // How remaining votes is calculated might depend on this. For now, assume backend provides current remaining.
                }
                if (config.max_votes_per_option !== undefined) {
                    summary.max_votes_per_option = config.max_votes_per_option;
                }

                setVotingError(null);
                setVotingStatus("");
                renderVotingSummary(summary);
            } catch (error) {
                setVotingError(error.message || "Unable to load voting options.");
                setVotingStatus("");
                votingTiming.end("exception", {
                    detail: error?.message || "Unable to load voting options.",
                });
            } finally {
                votingOptionsRefreshInFlight = false;
            }
        }

        function setCategorizationError(message) {
            if (!categorization.error) {
                return;
            }
            if (!message) {
                categorization.error.textContent = "";
                categorization.error.hidden = true;
                return;
            }
            categorization.error.textContent = message;
            categorization.error.hidden = false;
        }

        function bucketCountsFromState(summary, assignmentMap = null) {
            const counts = new Map();
            const assignments = assignmentMap || summary?.assignments || {};
            Object.values(assignments).forEach((categoryId) => {
                const key = String(categoryId || "UNSORTED");
                counts.set(key, (counts.get(key) || 0) + 1);
            });
            return counts;
        }

        async function moveCategorizationItem(itemKey, destinationCategoryId) {
            if (!categorizationActivityId) {
                return;
            }
            const url = `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/assignments`;
            const payload = {
                activity_id: categorizationActivityId,
                item_key: itemKey,
                category_id: destinationCategoryId,
            };
            const response = await fetch(url, {
                method: "POST",
                credentials: "include",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload),
            });
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to move categorization item.");
            }
        }

        async function reorderCategorizationBuckets(activityId, orderedCategoryIds) {
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/buckets/reorder`,
                {
                    method: "POST",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        activity_id: activityId,
                        category_ids: orderedCategoryIds,
                    }),
                },
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to reorder buckets.");
            }
        }

        async function renameCategorizationBucket(activityId, categoryId, currentTitle) {
            const title = window.prompt("Edit bucket title", currentTitle || "");
            if (!title || !title.trim()) {
                return;
            }
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/buckets/${encodeURIComponent(categoryId)}`,
                {
                    method: "PATCH",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        activity_id: activityId,
                        title: title.trim(),
                    }),
                },
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to edit bucket.");
            }
        }

        async function deleteCategorizationBucket(activityId, categoryId, bucketTitle) {
            const confirmed = window.confirm(
                `Delete bucket "${bucketTitle || categoryId}"? Items will move to Unsorted.`,
            );
            if (!confirmed) {
                return;
            }
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/buckets/${encodeURIComponent(categoryId)}`,
                {
                    method: "DELETE",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        activity_id: activityId,
                    }),
                },
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to delete bucket.");
            }
        }

        async function createCategorizationItem(activityId, content) {
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/items`,
                {
                    method: "POST",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        activity_id: activityId,
                        content,
                    }),
                },
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to add idea.");
            }
            return response.json();
        }

        async function renameCategorizationItem(activityId, itemKey, currentContent) {
            const content = window.prompt("Edit idea", currentContent || "");
            if (!content || !content.trim()) {
                return;
            }
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/items/${encodeURIComponent(itemKey)}`,
                {
                    method: "PATCH",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        activity_id: activityId,
                        content: content.trim(),
                    }),
                },
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to edit idea.");
            }
        }

        async function deleteCategorizationItem(activityId, itemKey, itemContent) {
            const confirmed = window.confirm(
                `Delete idea "${itemContent || itemKey}"?`,
            );
            if (!confirmed) {
                return;
            }
            const response = await fetch(
                `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/items/${encodeURIComponent(itemKey)}`,
                {
                    method: "DELETE",
                    credentials: "include",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        activity_id: activityId,
                    }),
                },
            );
            if (!response.ok) {
                const err = await response.json().catch(() => ({}));
                throw new Error(err.detail || "Unable to delete idea.");
            }
        }

        function renderCategorizationSummary(summary, eligibility) {
            categorizationState = summary || null;
            if (categorization.instructions) {
                categorization.instructions.textContent = "Facilitator-live mode is active. Buckets and assignments update for everyone in real time.";
            }
            if (!categorization.itemsList || !categorization.bucketsList) {
                return;
            }
            categorization.itemsList.innerHTML = "";
            categorization.bucketsList.innerHTML = "";
            if (!summary || !Array.isArray(summary.items)) {
                const empty = document.createElement("li");
                empty.className = "categorization-item-empty";
                empty.textContent = "No items available.";
                categorization.itemsList.appendChild(empty);
                const emptyBucket = document.createElement("li");
                emptyBucket.className = "categorization-item-empty";
                emptyBucket.textContent = "No buckets available.";
                categorization.bucketsList.appendChild(emptyBucket);
                return;
            }

            const isFacilitator = Boolean(state.isFacilitator);
            const mode = String(summary.mode || "FACILITATOR_LIVE").toUpperCase();
            const assignments = summary.assignments || {};
            const buckets = Array.isArray(summary.buckets) ? summary.buckets : [];
            const effectiveAssignments = assignments;
            const counts = bucketCountsFromState(summary, effectiveAssignments);

            if (!categorizationSelectedBucketId || !buckets.some((bucket) => bucket.category_id === categorizationSelectedBucketId)) {
                const preferred = buckets.find((bucket) => bucket.category_id === "UNSORTED");
                categorizationSelectedBucketId = preferred?.category_id || buckets[0]?.category_id || null;
            }

            const sortedBuckets = [...buckets].sort((a, b) => {
                const aId = String(a.category_id || "");
                const bId = String(b.category_id || "");
                if (aId === "UNSORTED" && bId !== "UNSORTED") return -1;
                if (bId === "UNSORTED" && aId !== "UNSORTED") return 1;
                return Number(a.order_index || 0) - Number(b.order_index || 0);
            });

            if (buckets.length === 0) {
                const emptyBucket = document.createElement("li");
                emptyBucket.className = "categorization-item-empty";
                emptyBucket.textContent = "No buckets available.";
                categorization.bucketsList.appendChild(emptyBucket);
            } else {
                const canManageBuckets = mode === "FACILITATOR_LIVE" && isFacilitator && categorizationIsActive;
                const collectBucketOrder = () => {
                    const order = [];
                    if (!categorization.bucketsList) {
                        return order;
                    }
                    categorization.bucketsList.querySelectorAll(".categorization-bucket-item").forEach((entry) => {
                        const value = String(entry.dataset.categoryId || "").trim();
                        if (value) {
                            order.push(value);
                        }
                    });
                    return order;
                };
                const handlePersistBucketOrder = async () => {
                    if (!categorizationActivityId) {
                        return;
                    }
                    const orderedCategoryIds = collectBucketOrder();
                    if (!orderedCategoryIds.length) {
                        return;
                    }
                    try {
                        setCategorizationError(null);
                        await reorderCategorizationBuckets(categorizationActivityId, orderedCategoryIds);
                        await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                    } catch (error) {
                        setCategorizationError(error.message || "Unable to reorder buckets.");
                    } finally {
                        categorizationDraggedBucketId = null;
                    }
                };

                sortedBuckets.forEach((bucket) => {
                    const bucketId = String(bucket.category_id || "");
                    const displayTitle = bucketId === "UNSORTED"
                        ? "Unsorted Ideas"
                        : (bucket.title || bucket.category_id || "Bucket");
                    const li = document.createElement("li");
                    li.className = "categorization-bucket-item";
                    li.dataset.categoryId = bucketId;
                    if (bucketId === categorizationSelectedBucketId) {
                        li.classList.add("is-selected");
                    }
                    const row = document.createElement("div");
                    row.className = "categorization-bucket-row";
                    const title = document.createElement("span");
                    title.className = "categorization-bucket-title";
                    title.textContent = displayTitle;
                    const count = document.createElement("span");
                    count.className = "categorization-bucket-count";
                    count.textContent = `${counts.get(bucketId) || 0} items`;
                    row.append(title, count);
                    li.appendChild(row);
                    li.addEventListener("click", () => {
                        categorizationSelectedBucketId = bucketId;
                        renderCategorizationSummary(categorizationState, eligibility);
                    });
                    if (canManageBuckets && bucketId !== "UNSORTED") {
                        li.draggable = true;
                        li.classList.add("is-draggable");
                        li.addEventListener("dragstart", (event) => {
                            categorizationDraggedItemKey = null;
                            categorizationDraggedBucketId = bucketId;
                            if (event.dataTransfer) {
                                event.dataTransfer.setData("text/x-cat-bucket", bucketId);
                                event.dataTransfer.effectAllowed = "move";
                            }
                        });
                    }
                    if (canManageBuckets) {
                        li.addEventListener("dragover", (event) => {
                            event.preventDefault();
                            li.classList.add("is-drop-target");
                        });
                        li.addEventListener("dragleave", () => {
                            li.classList.remove("is-drop-target");
                        });
                        li.addEventListener("drop", async (event) => {
                            event.preventDefault();
                            li.classList.remove("is-drop-target");
                            const itemKey = event.dataTransfer?.getData("text/x-cat-item")
                                || event.dataTransfer?.getData("text/plain")
                                || categorizationDraggedItemKey;
                            if (itemKey) {
                                try {
                                    setCategorizationError(null);
                                    await moveCategorizationItem(itemKey, bucketId);
                                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                                } catch (error) {
                                    setCategorizationError(error.message || "Unable to move categorization item.");
                                } finally {
                                    categorizationDraggedItemKey = null;
                                }
                                return;
                            }
                            const draggedBucket = event.dataTransfer?.getData("text/x-cat-bucket") || categorizationDraggedBucketId;
                            if (draggedBucket) {
                                if (draggedBucket === "UNSORTED" || draggedBucket === bucketId) {
                                    return;
                                }
                                const sourceEntry = categorization.bucketsList?.querySelector(
                                    `.categorization-bucket-item[data-category-id="${CSS.escape(draggedBucket)}"]`,
                                );
                                if (sourceEntry && sourceEntry !== li) {
                                    li.parentElement?.insertBefore(sourceEntry, li);
                                    await handlePersistBucketOrder();
                                }
                            }
                        });
                        li.addEventListener("dragend", () => {
                            categorizationDraggedBucketId = null;
                            li.classList.remove("is-drop-target");
                        });
                    }
                    categorization.bucketsList.appendChild(li);
                });
            }

            const openBucket = buckets.find((bucket) => bucket.category_id === categorizationSelectedBucketId) || null;
            const openBucketCount = counts.get(String(categorizationSelectedBucketId || "UNSORTED")) || 0;
            if (categorization.openBucketTitle) {
                const bucketLabel = categorizationSelectedBucketId === "UNSORTED"
                    ? "Unsorted Ideas"
                    : (openBucket?.title || categorizationSelectedBucketId || "Open Bucket");
                categorization.openBucketTitle.textContent = `Open Bucket Contents: ${bucketLabel} (${openBucketCount})`;
            }

            const visibleItems = mode === "FACILITATOR_LIVE"
                ? summary.items.filter((item) => {
                    const itemKey = item.item_key;
                    return String(effectiveAssignments[itemKey] || "UNSORTED") === String(categorizationSelectedBucketId || "UNSORTED");
                })
                : summary.items;

            const orderKey = `${summary.activity_id || categorizationActivityId || "unknown"}:${categorizationSelectedBucketId || "UNSORTED"}`;
            const existingOrder = categorizationItemOrder.get(orderKey) || [];
            const visibleKeys = visibleItems.map((item) => String(item.item_key || ""));
            const mergedOrder = existingOrder.filter((key) => visibleKeys.includes(key));
            visibleKeys.forEach((key) => {
                if (!mergedOrder.includes(key)) {
                    mergedOrder.push(key);
                }
            });
            categorizationItemOrder.set(orderKey, mergedOrder);
            const rankByItemKey = new Map(mergedOrder.map((key, index) => [key, index]));
            const orderedVisibleItems = [...visibleItems].sort((a, b) => {
                const aRank = rankByItemKey.get(String(a.item_key || ""));
                const bRank = rankByItemKey.get(String(b.item_key || ""));
                const left = Number.isFinite(aRank) ? aRank : Number.MAX_SAFE_INTEGER;
                const right = Number.isFinite(bRank) ? bRank : Number.MAX_SAFE_INTEGER;
                return left - right;
            });
            const visibleItemKeys = orderedVisibleItems.map((item) => String(item.item_key || ""));
            if (
                !categorizationSelectedItemKey
                || !visibleItemKeys.includes(String(categorizationSelectedItemKey))
            ) {
                categorizationSelectedItemKey = visibleItemKeys[0] || null;
            }

            if (orderedVisibleItems.length === 0) {
                categorizationSelectedItemKey = null;
                const empty = document.createElement("li");
                empty.className = "categorization-item-empty";
                empty.textContent = mode === "FACILITATOR_LIVE"
                    ? "No items in this bucket."
                    : "No items available.";
                categorization.itemsList.appendChild(empty);
            } else {
                orderedVisibleItems.forEach((item) => {
                    const itemKey = item.item_key;
                    const effectiveCategory = String(effectiveAssignments[itemKey] || "UNSORTED");
                    const li = document.createElement("li");
                    li.dataset.itemKey = String(itemKey || "");
                    if (String(categorizationSelectedItemKey || "") === String(itemKey || "")) {
                        li.classList.add("is-selected");
                    }
                    if (mode === "FACILITATOR_LIVE" && isFacilitator) {
                        li.addEventListener("click", () => {
                            categorizationSelectedItemKey = itemKey;
                            renderCategorizationSummary(categorizationState, eligibility);
                        });
                    }
                    const main = document.createElement("div");
                    main.className = "categorization-item-main";
                    if (mode === "FACILITATOR_LIVE" && isFacilitator && categorizationIsActive) {
                        li.draggable = true;
                        li.classList.add("is-draggable");
                        li.addEventListener("dragstart", (event) => {
                            categorizationDraggedBucketId = null;
                            categorizationDraggedItemKey = itemKey;
                            if (event.dataTransfer) {
                                event.dataTransfer.setData("text/x-cat-item", itemKey);
                                event.dataTransfer.setData("text/plain", itemKey);
                                event.dataTransfer.effectAllowed = "move";
                            }
                        });
                        li.addEventListener("dragend", () => {
                            categorizationDraggedItemKey = null;
                            li.classList.remove("is-drop-target");
                        });
                        li.addEventListener("dragover", (event) => {
                            const draggedItemKey = event.dataTransfer?.getData("text/x-cat-item")
                                || event.dataTransfer?.getData("text/plain")
                                || categorizationDraggedItemKey;
                            if (!draggedItemKey) {
                                return;
                            }
                            event.preventDefault();
                            li.classList.add("is-drop-target");
                        });
                        li.addEventListener("dragleave", () => {
                            li.classList.remove("is-drop-target");
                        });
                        li.addEventListener("drop", (event) => {
                            const draggedItemKey = event.dataTransfer?.getData("text/x-cat-item")
                                || event.dataTransfer?.getData("text/plain")
                                || categorizationDraggedItemKey;
                            const targetItemKey = String(itemKey || "");
                            li.classList.remove("is-drop-target");
                            if (!draggedItemKey || String(draggedItemKey) === targetItemKey) {
                                return;
                            }
                            event.preventDefault();
                            const current = [...(categorizationItemOrder.get(orderKey) || [])];
                            const sourceIndex = current.indexOf(String(draggedItemKey));
                            const targetIndex = current.indexOf(targetItemKey);
                            if (sourceIndex < 0 || targetIndex < 0) {
                                return;
                            }
                            const [entry] = current.splice(sourceIndex, 1);
                            const targetRect = li.getBoundingClientRect();
                            const dropInLowerHalf = event.clientY > (targetRect.top + targetRect.height / 2);
                            const adjustedTargetIndex = current.indexOf(targetItemKey);
                            const insertIndex = dropInLowerHalf ? adjustedTargetIndex + 1 : adjustedTargetIndex;
                            current.splice(insertIndex, 0, entry);
                            categorizationItemOrder.set(orderKey, current);
                            renderCategorizationSummary(categorizationState, eligibility);
                        });
                    }
                    const text = document.createElement("div");
                    text.textContent = item.content || item.item_key || "Item";
                    main.append(text);

                    li.appendChild(main);
                    categorization.itemsList.appendChild(li);
                });
            }

            const showFacilitatorControls = isFacilitator;
            if (categorization.addBucket) categorization.addBucket.hidden = !showFacilitatorControls || mode !== "FACILITATOR_LIVE";
            if (categorization.editBucket) categorization.editBucket.hidden = !showFacilitatorControls || mode !== "FACILITATOR_LIVE";
            if (categorization.deleteBucket) categorization.deleteBucket.hidden = !showFacilitatorControls || mode !== "FACILITATOR_LIVE";
            if (categorization.addItem) categorization.addItem.hidden = !showFacilitatorControls || mode !== "FACILITATOR_LIVE";
            if (categorization.editItem) categorization.editItem.hidden = !showFacilitatorControls || mode !== "FACILITATOR_LIVE";
            if (categorization.deleteItem) categorization.deleteItem.hidden = !showFacilitatorControls || mode !== "FACILITATOR_LIVE";
            if (categorization.addBucket) categorization.addBucket.disabled = !showFacilitatorControls || mode !== "FACILITATOR_LIVE" || !categorizationIsActive;
            if (categorization.addItem) categorization.addItem.disabled = !showFacilitatorControls || mode !== "FACILITATOR_LIVE" || !categorizationIsActive;
            const selectedIsUnsorted = String(categorizationSelectedBucketId || "") === "UNSORTED";
            if (categorization.editBucket) categorization.editBucket.disabled = !showFacilitatorControls || selectedIsUnsorted || mode !== "FACILITATOR_LIVE" || !categorizationIsActive;
            if (categorization.deleteBucket) categorization.deleteBucket.disabled = !showFacilitatorControls || selectedIsUnsorted || mode !== "FACILITATOR_LIVE" || !categorizationIsActive;
            const hasSelectedItem = Boolean(categorizationSelectedItemKey);
            const canManageIdeas = showFacilitatorControls && mode === "FACILITATOR_LIVE" && categorizationIsActive;
            if (categorization.editItem) categorization.editItem.disabled = !canManageIdeas || !hasSelectedItem;
            if (categorization.deleteItem) categorization.deleteItem.disabled = !canManageIdeas || !hasSelectedItem;
        }

        async function loadCategorizationState(activityId, config = {}, { force = false } = {}) {
            if (!categorization.root || !activityId || (categorizationRequestInFlight && !force)) {
                return;
            }
            categorizationRequestInFlight = true;
            try {
                const rawMode = String(config.mode || "FACILITATOR_LIVE").toUpperCase();
                const mode = rawMode === "PARALLEL_BALLOT" ? "FACILITATOR_LIVE" : rawMode;
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/state?activity_id=${encodeURIComponent(activityId)}`,
                    { credentials: "include" },
                );
                if (!response.ok) {
                    const err = await response.json().catch(() => ({}));
                    throw new Error(err.detail || "Unable to load categorization state.");
                }
                const summary = await response.json();
                summary.mode = mode;
                summary.locked = Boolean(config.locked);
                renderCategorizationSummary(summary);
                setCategorizationError(null);
            } catch (error) {
                renderCategorizationSummary(null);
                setCategorizationError(error.message || "Unable to load categorization state.");
            } finally {
                categorizationRequestInFlight = false;
            }
        }

        function setBrainstormingFormEnabled(enabled, config) {
            if (!brainstorming.form) {
                return;
            }
            if (config !== undefined && config !== null) {
                activeBrainstormingConfig = config || {};
            }
            syncBrainstormingAutoJumpToggle();
            const disabled = !enabled || brainstormingSubmitInFlight;
            if (brainstorming.textarea) {
                brainstorming.textarea.disabled = disabled;
                const maxLength =
                    (activeBrainstormingConfig && activeBrainstormingConfig.idea_character_limit) ||
                    brainstormingLimits.ideaCharacterLimit;
                if (maxLength && Number(maxLength) > 0) {
                    brainstorming.textarea.setAttribute("maxlength", maxLength);
                } else {
                    brainstorming.textarea.removeAttribute("maxlength");
                }
            }
            updateSubmitButtonState();
        }

        async function loadBrainstormingIdeas(activityId, config = {}) {
            if (!activityId || brainstormingIdeasLoaded || !brainstorming.root) {
                return;
            }
            try {
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/brainstorming/ideas?activity_id=${encodeURIComponent(activityId)}`,
                    { credentials: "include" },
                );
                if (!response.ok) {
                    if (response.status === 401 || response.status === 403) {
                        setBrainstormingError("Session expired. Please refresh and log in again.");
                        setBrainstormingFormEnabled(false);
                        return;
                    }
                    throw new Error(`Failed to load ideas (${response.status})`);
                }
                const ideas = await response.json();
                console.info("brainstorming ideas loaded", {
                    activityId,
                    count: Array.isArray(ideas) ? ideas.length : 0,
                });
                brainstormingIdeasLoaded = true;
                setBrainstormingError(null);
                renderIdeas(ideas);
            } catch (error) {
                console.error("Unable to load brainstorming ideas", error);
                setBrainstormingError("Unable to load existing ideas. Try again later.");
            }
        }

        async function submitIdea(content) {
            if (!brainstormingActivityId) {
                setBrainstormingError("No active brainstorming activity selected.");
                return;
            }
            try {
                setBrainstormingError(null);
                brainstormingSubmitInFlight = true;
                setBrainstormingFormEnabled(true);

                const payload = { content };
                const submitUrl = `/api/meetings/${encodeURIComponent(context.meetingId)}/brainstorming/ideas?activity_id=${encodeURIComponent(brainstormingActivityId)}`;
                const response = await runReliableWriteAction({
                    toolType: "brainstorming",
                    actionName: "submit_idea",
                    queueName: "brainstorming-submit",
                    fallbackPolicy: {
                        maxRetries: 3,
                        baseDelayMs: 400,
                        maxDelayMs: 2500,
                        jitterRatio: 0.25,
                    },
                    requestFactory: ({ attempt, requestId, policy }) => fetch(submitUrl, {
                            method: "POST",
                            credentials: "include",
                            headers: {
                                "Content-Type": "application/json",
                                [policy.idempotencyHeader]: requestId || "",
                                "X-Retry-Attempt": String(attempt),
                            },
                            body: JSON.stringify(payload),
                        }),
                    onRetry: ({ attempt }) => {
                        setBrainstormingError(`Connection busy. Retrying submit (${attempt + 1})…`);
                    },
                });

                if (!response.ok) {
                    const errorPayload = await response.json().catch(() => ({}));
                    if (response.status === 401 || response.status === 403) {
                        setBrainstormingError("Session expired. Please refresh and log in again.");
                        setBrainstormingFormEnabled(false);
                        throw new Error("Session expired.");
                    }
                    if (response.status === 429 || response.status === 503) {
                        throw new Error(
                            errorPayload.detail || "Server is temporarily busy. Please try again shortly.",
                        );
                    }
                    throw new Error(errorPayload.detail || "Unable to submit idea");
                }

                const createdIdea = await response.json();
                appendIdea(createdIdea);
                if (brainstorming.textarea) {
                    brainstorming.textarea.value = "";
                }
                updateSubmitButtonState();
            } catch (error) {
                setBrainstormingError(error.message || "Unable to submit idea. Please try again.");
            } finally {
                brainstormingSubmitInFlight = false;
                setBrainstormingFormEnabled(true);
                updateSubmitButtonState();
                if (brainstormingActive && brainstorming.textarea && !brainstorming.textarea.disabled) {
                    brainstorming.textarea.focus();
                }
            }
        }

        function formatConfigLabel(key) {
            if (CONFIG_LABEL_MAP[key]) return CONFIG_LABEL_MAP[key];
            return key
                .replace(/_/g, " ")
                .replace(/\b\w/g, (letter) => letter.toUpperCase());
        }

        function getModuleMeta(toolType) {
            return state.moduleMap.get((toolType || "").toLowerCase()) || state.moduleMap.get(toolType) || null;
        }

        function getReliableQueue(name) {
            const key = String(name || "default");
            if (reliableActionQueues.has(key)) {
                return reliableActionQueues.get(key);
            }
            const queue = window.DecideroReliableActions
                ? window.DecideroReliableActions.createSerialQueue(key)
                : {
                    enqueue(task) {
                        return task();
                    },
                };
            reliableActionQueues.set(key, queue);
            return queue;
        }

        function resolveWriteReliabilityPolicy(toolType, actionName, fallback = {}) {
            const moduleMeta = getModuleMeta(toolType) || {};
            const policy = moduleMeta.reliability_policy || {};
            const actionPolicy = policy[actionName] || policy.write_default || {};
            const merged = {
                ...writeReliabilityDefaults,
                ...(fallback || {}),
            };

            const statuses = Array.isArray(actionPolicy.retryable_statuses)
                ? actionPolicy.retryable_statuses
                    .map((value) => Number.parseInt(value, 10))
                    .filter((value) => Number.isFinite(value))
                : null;
            if (statuses && statuses.length) {
                merged.retryableStatuses = statuses;
            }

            const maxRetries = Number.parseInt(actionPolicy.max_retries, 10);
            if (Number.isFinite(maxRetries)) merged.maxRetries = Math.max(0, maxRetries);
            const baseDelayMs = Number.parseInt(actionPolicy.base_delay_ms, 10);
            if (Number.isFinite(baseDelayMs)) merged.baseDelayMs = Math.max(1, baseDelayMs);
            const maxDelayMs = Number.parseInt(actionPolicy.max_delay_ms, 10);
            if (Number.isFinite(maxDelayMs)) merged.maxDelayMs = Math.max(merged.baseDelayMs, maxDelayMs);
            const jitterRatio = Number.parseFloat(actionPolicy.jitter_ratio);
            if (Number.isFinite(jitterRatio)) merged.jitterRatio = Math.max(0, jitterRatio);
            if (typeof actionPolicy.idempotency_header === "string" && actionPolicy.idempotency_header.trim()) {
                merged.idempotencyHeader = actionPolicy.idempotency_header.trim();
            }
            return merged;
        }

        async function runReliableWriteAction({
            toolType,
            actionName,
            queueName,
            fallbackPolicy,
            requestFactory,
            onRetry,
        }) {
            const queue = getReliableQueue(queueName || `${toolType}-${actionName}`);
            const policy = resolveWriteReliabilityPolicy(toolType, actionName, fallbackPolicy);
            return queue.enqueue(() => {
                const reliableActions = window.DecideroReliableActions;
                if (!reliableActions || typeof reliableActions.runWithRetry !== "function") {
                    return requestFactory({ attempt: 0, requestId: null, policy });
                }
                const retryableStatusSet = new Set(policy.retryableStatuses || []);
                return reliableActions.runWithRetry(
                    ({ attempt, requestId }) => requestFactory({ attempt, requestId, policy }),
                    {
                        maxRetries: policy.maxRetries,
                        baseDelayMs: policy.baseDelayMs,
                        maxDelayMs: policy.maxDelayMs,
                        jitterRatio: policy.jitterRatio,
                        shouldRetryResult: (result) => Boolean(
                            result && retryableStatusSet.has(result.status),
                        ),
                        onRetry,
                    },
                );
            });
        }

        let currentDraggedItem = null; // Global variable to store the currently dragged item

        // Function to send reorder API request
        async function sendReorderRequest(newOrderIds) {
            setFacilitatorFeedback("Reordering agenda…", "info");
            try {
                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/agenda-reorder`,
                    {
                        method: "PUT",
                        headers: { "Content-Type": "application/json" },
                        credentials: "include",
                        body: JSON.stringify({ activity_ids: newOrderIds }),
                    },
                );

                if (!response.ok) {
                    const errorData = await response.json().catch(() => ({}));
                    throw new Error(errorData.detail || "Failed to reorder agenda.");
                }
                setFacilitatorFeedback("Agenda reordered successfully!", "success");
                // Agenda will be re-rendered by the WebSocket update
            } catch (error) {
                console.error("Error reordering agenda:", error);
                setFacilitatorFeedback(error.message || "An unexpected error occurred during reorder.", "error");
            }
        }

        async function deleteActivity(activityId, options = {}) {
            if (!state.isFacilitator || !activityId) {
                return;
            }
            const currentlyActive = Boolean(options.isRunning || options.isPaused);
            if (currentlyActive) {
                const proceed = confirm(
                    "This activity is currently running or paused. It must be stopped before deletion. Stop and continue?",
                );
                if (!proceed) {
                    return;
                }
                try {
                    if (ui.statusBadge) {
                        setStatus("Stopping activity before delete...", "info");
                    }
                    await sendControl("stop_tool", { activityId });
                    // Allow state to settle before issuing delete.
                    await new Promise((resolve) => setTimeout(resolve, 350));
                } catch (error) {
                    console.error("Unable to stop activity before delete:", error);
                    setFacilitatorFeedback(
                        error.message || "Unable to stop activity. Delete cancelled.",
                        "error",
                    );
                    return;
                }
            }
            if (!confirm("Are you sure you want to delete this activity? This cannot be undone.")) {
                return;
            }
            setFacilitatorFeedback("Deleting activity…", "info");
            try {
                const deleteOnce = async () => fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/agenda/${encodeURIComponent(activityId)}`,
                    {
                        method: "DELETE",
                        credentials: "include",
                    },
                );
                let response = await deleteOnce();
                if (!response.ok) {
                    let errorData = await response.json().catch(() => ({}));
                    const detail = String(errorData.detail || "");
                    if (detail.toLowerCase().includes("cannot delete an active activity")) {
                        // The backend is authoritative; refresh once and retry.
                        await new Promise((resolve) => setTimeout(resolve, 350));
                        response = await deleteOnce();
                        if (!response.ok) {
                            errorData = await response.json().catch(() => ({}));
                        }
                    }
                    if (!response.ok) {
                        throw new Error(errorData.detail || "Failed to delete activity.");
                    }
                }
                const filtered = (state.agenda || []).filter((item) => item.activity_id !== activityId);
                state.agenda = filtered;
                state.agendaMap = new Map(state.agenda.map((item) => [item.activity_id, item]));
                if (state.latestState && Array.isArray(state.latestState.agenda)) {
                    state.latestState.agenda = filtered;
                }
                if (state.selectedActivityId === activityId) {
                    state.selectedActivityId = null;
                }
                renderAgenda(filtered);
                updateAgendaSummary();

                setFacilitatorFeedback("Activity deleted successfully!", "success");

                // Ensure the agenda list refreshes even if realtime is delayed/unavailable.
                fetch(`/api/meetings/${encodeURIComponent(context.meetingId)}/agenda`, {
                    credentials: "include",
                    cache: "no-store",
                })
                    .then((res) => (res.ok ? res.json() : Promise.reject(new Error("Unable to refresh agenda."))))
                    .then((agenda) => {
                        if (Array.isArray(agenda)) {
                            state.agenda = agenda;
                            state.agendaMap = new Map(agenda.map((item) => [item.activity_id, item]));
                            if (state.latestState) {
                                state.latestState.agenda = agenda;
                            }
                            renderAgenda(agenda);
                            updateAgendaSummary();
                        }
                    })
                    .catch((error) => {
                        console.warn("Agenda refresh after delete failed:", error);
                    });
            } catch (error) {
                console.error("Error deleting activity:", error);
                setFacilitatorFeedback(error.message || "An unexpected error occurred.", "error");
            }
        }

        function renderAgenda(agenda) {
            if (!ui.agendaList) {
                return;
            }

            const previousAgendaMap = state.agendaMap instanceof Map ? state.agendaMap : new Map();
            state.agenda = Array.isArray(agenda)
                ? [...agenda].sort((a, b) => (a.order_index || 0) - (b.order_index || 0))
                    .map((item) => {
                        const previous = previousAgendaMap.get(item?.activity_id);
                        if (!previous) {
                            return item;
                        }
                        if (
                            item?.transfer_count === undefined &&
                            item?.transferable_count === undefined &&
                            (previous.transfer_count !== undefined || previous.transferable_count !== undefined)
                        ) {
                            return {
                                ...item,
                                transfer_count: Number(
                                    previous.transfer_count ?? previous.transferable_count ?? 0,
                                ),
                                transfer_source: item.transfer_source ?? previous.transfer_source,
                                transfer_reason: item.transfer_reason ?? previous.transfer_reason,
                            };
                        }
                        return item;
                    })
                : [];
            state.agendaMap = new Map(state.agenda.map((item) => [item.activity_id, item]));
            ui.agendaList.innerHTML = "";

            if (state.agenda.length === 0) {
                const empty = document.createElement("li");
                empty.className = "agenda-item agenda-item-empty";
                empty.textContent = "No activities have been scheduled yet.";
                ui.agendaList.appendChild(empty);
                updateAgendaSummary();
                return;
            }

            // Make the agenda list a drop target for reordering
            ui.agendaList.addEventListener("dragover", (e) => {
                e.preventDefault(); // Allow drop
                const dragging = document.querySelector(".dragging");
                if (!dragging) return;
                const afterElement = getDragAfterElement(ui.agendaList, e.clientY);
                if (afterElement == null) {
                    ui.agendaList.appendChild(dragging);
                } else {
                    ui.agendaList.insertBefore(dragging, afterElement);
                }
            });

            ui.agendaList.addEventListener("drop", async (e) => {
                e.preventDefault();
                if (currentDraggedItem) {
                    currentDraggedItem.classList.remove("dragging");
                    currentDraggedItem = null;

                    // Get new order of activity IDs
                    const newOrderIds = Array.from(ui.agendaList.children)
                        .map(item => item.dataset.activityId)
                        .filter(Boolean); // Ensure no null/undefined

                    if (newOrderIds.length > 0) {
                        await sendReorderRequest(newOrderIds);
                    }
                }
            });


            state.agenda.forEach((item) => {
                const moduleMeta = getModuleMeta(item.tool_type) || { label: item.tool_type };

                const li = document.createElement("li");
                li.className = "agenda-item";
                li.dataset.activityId = item.activity_id;

                // Make draggable for facilitators
                if (state.isFacilitator) {
                    li.draggable = true;
                    li.addEventListener("dragstart", (e) => {
                        currentDraggedItem = li;
                        setTimeout(() => li.classList.add("dragging"), 0); // Add class after a brief delay
                    });
                    li.addEventListener("dragend", () => {
                        li.classList.remove("dragging");
                        currentDraggedItem = null;
                    });
                }

                const header = document.createElement("div");
                header.className = "agenda-item-header";
                const title = document.createElement("span");
                title.textContent = `${item.order_index ?? ""}. ${item.title}`;
                const tool = document.createElement("span");
                tool.className = "agenda-item-tool";
                tool.textContent = moduleMeta.label;
                header.append(title, tool);

                const metaRow = document.createElement("div");
                metaRow.className = "agenda-item-meta";
                const instructions = (item.instructions || "").trim();
                metaRow.textContent = instructions || "";

                const controlsRow = document.createElement("div");
                controlsRow.className = "agenda-item-controls";
                const badges = document.createElement("div");
                badges.className = "agenda-item-badges";
                const actions = document.createElement("div");
                actions.className = "agenda-item-actions";

                // Determine status
                const activityState = state.activeActivities?.[item.activity_id] || null;
                const statusSource = activityState || (state.latestState?.currentActivity === item.activity_id ? state.latestState : null);
                const status = (statusSource?.status || "stopped").toLowerCase();
                const isRunning = status === "in_progress";
                const isPaused = status === "paused";
                const isActive = isRunning || isPaused || state.latestState?.currentActivity === item.activity_id;
                const elapsed = activityState?.elapsedTime || item.elapsed_duration || 0;

                const statusContainer = document.createElement("div");
                statusContainer.className = "agenda-item-status-container";

                // Status Icon
                const statusIcon = document.createElement("span");
                statusIcon.className = "agenda-item-icon";
                statusIcon.textContent = isRunning ? "▶" : (isPaused ? "⏸" : "■");
                statusIcon.title = isRunning ? "Running" : (isPaused ? "Paused" : "Stopped");
                statusIcon.dataset.state = status;

                // Time Display
                const timeDisplay = document.createElement("span");
                timeDisplay.className = "agenda-item-timer";
                timeDisplay.dataset.activityId = item.activity_id;
                timeDisplay.dataset.baseElapsed = elapsed;
                timeDisplay.dataset.startedAt = activityState?.startedAt || statusSource?.startedAt || "";
                timeDisplay.textContent = formatDuration(elapsed);

                statusContainer.append(statusIcon, timeDisplay);
                badges.appendChild(statusContainer);

                const rosterSummary = getActivityRosterSummary(item.activity_id);
                if (rosterSummary) {
                    const rosterBadge = document.createElement("span");
                    rosterBadge.className = "agenda-item-roster";
                    rosterBadge.dataset.live = rosterSummary.isLive ? "true" : "false";
                    rosterBadge.textContent = rosterSummary.text;
                    badges.appendChild(rosterBadge);
                }

                const activeCount = getActiveParticipantCount(item, activityState);
                if (activeCount !== null) {
                    const activeBadge = document.createElement("span");
                    activeBadge.className = "agenda-item-active-count";
                    activeBadge.textContent = `Active now • ${activeCount}`;
                    badges.appendChild(activeBadge);
                }

                const accessState = getActivityAccessState(item, activityState, isActive);
                li.dataset.access = accessState.isOpen ? "open" : "closed";
                li.dataset.enterable = accessState.canEnter ? "true" : "false";
                const accessBadge = document.createElement("span");
                accessBadge.className = "agenda-item-access";
                accessBadge.dataset.state = accessState.isOpen ? "open" : "closed";
                accessBadge.textContent = accessState.isOpen ? "Open" : "Closed";
                accessBadge.title = accessState.title || (accessState.isOpen ? "Open to you now" : "Closed to you");
                badges.appendChild(accessBadge);

                if (state.isFacilitator) {
                    // Start Button (Handles Start and Resume)
                    const startBtn = document.createElement("button");
                    startBtn.type = "button";
                    startBtn.className = "control-btn primary sm";
                    startBtn.textContent = "Start";
                    startBtn.disabled = isRunning; // Disabled if already running
                    startBtn.title = isPaused ? "Resume Activity" : "Start Activity";

                    startBtn.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        // Resume if paused, otherwise start
                        const action = isPaused ? "resume_tool" : "start_tool";
                        try {
                            // Optimistic UI update
                            if (ui.statusBadge) setStatus("Starting activity...", "info");
                            await sendControl(action, { tool: item.tool_type, activityId: item.activity_id });
                        } catch (error) {
                            if (error.isConflict && error.conflictDetails) {
                                showCollisionModal(error.conflictDetails.conflicting_users, error.conflictDetails.active_activity_id);
                            } else {
                                console.error(error);
                                alert(error.message || "Unable to start activity.");
                            }
                            setStatus("Ready", "error");
                        }
                    });
                    actions.appendChild(startBtn);

                    // Stop Button
                    const stopBtn = document.createElement("button");
                    stopBtn.type = "button";
                    stopBtn.className = "control-btn sm destructive";
                    stopBtn.textContent = "Stop";
                    stopBtn.disabled = !isRunning && !isPaused; // Only enabled if running or paused

                    stopBtn.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        try {
                            if (ui.statusBadge) setStatus("Stopping activity...", "info");
                            await sendControl("stop_tool", { activityId: item.activity_id });
                        } catch (error) {
                            console.error(error);
                            alert(error.message || "Unable to stop activity.");
                        }
                    });
                    actions.appendChild(stopBtn);

                    // Manage Participants Button
                    const participantsBtn = document.createElement("button");
                    participantsBtn.type = "button";
                    participantsBtn.className = "control-btn sm";
                    participantsBtn.textContent = "Edit Roster";
                    participantsBtn.title = "Manage participants for this activity";
                    participantsBtn.addEventListener("click", (e) => {
                        e.stopPropagation();
                        selectAgendaItem(item.activity_id, { source: "user" });
                        openActivityParticipantModal(item.activity_id);
                    });
                    actions.appendChild(participantsBtn);

                    const transferCount = Number(item.transfer_count ?? item.transferable_count ?? 0);
                    const hasTransferItems = Number.isFinite(transferCount) && transferCount > 0;
                    const transferBtn = document.createElement("button");
                    transferBtn.type = "button";
                    transferBtn.className = "control-btn transfer-ideas-btn";
                    transferBtn.textContent = hasTransferItems
                        ? `Transfer Ideas (${transferCount})`
                        : "Transfer Ideas";
                    transferBtn.disabled = isRunning || !hasTransferItems;
                    if (isRunning) {
                        transferBtn.title = "Stop the activity before transferring ideas.";
                    } else if (!hasTransferItems) {
                        transferBtn.title = item.transfer_reason || "No ideas to transfer yet.";
                    } else {
                        transferBtn.title = "Transfer ideas to a new activity.";
                    }
                    transferBtn.addEventListener("click", (e) => {
                        e.stopPropagation();
                        if (transferBtn.disabled) {
                            return;
                        }
                        selectAgendaItem(item.activity_id, { source: "user" });
                        openTransferModal(item);
                    });
                    actions.appendChild(transferBtn);
                }

                // Add delete button for facilitators
                if (state.isFacilitator) {
                    const deleteBtn = document.createElement("button");
                    deleteBtn.type = "button";
                    deleteBtn.className = "control-btn agenda-item-delete-btn";
                    deleteBtn.textContent = "✖";
                    deleteBtn.title = isActive
                        ? "Stop required before delete"
                        : "Delete Activity";
                    deleteBtn.addEventListener("click", async (e) => {
                        e.stopPropagation();
                        await deleteActivity(item.activity_id, { isRunning, isPaused });
                    });
                    actions.appendChild(deleteBtn);
                }

                controlsRow.append(badges, actions);

                if (instructions) {
                    li.append(header, metaRow, controlsRow);
                } else {
                    li.append(header, controlsRow);
                }

                li.addEventListener("click", () => {
                    if (!accessState.canEnter) {
                        showAccessMessage(accessState.title || "You do not have access to this activity.");
                        return;
                    }
                    showAccessMessage("");
                    selectAgendaItem(item.activity_id, { source: "user" });
                });

                ui.agendaList.appendChild(li);
            });

            highlightAgenda();
            updateAgendaSummary();
        }

        function getDragAfterElement(container, y) {
            const draggableElements = [...container.querySelectorAll(".agenda-item:not(.dragging)")];

            return draggableElements.reduce((closest, child) => {
                const box = child.getBoundingClientRect();
                const offset = y - box.top - box.height / 2;
                if (offset < 0 && offset > closest.offset) {
                    return { offset: offset, element: child };
                } else {
                    return closest;
                }
            }, { offset: Number.NEGATIVE_INFINITY }).element;
        }

        function highlightAgenda() {
            if (!ui.agendaList) {
                return;
            }
            const items = ui.agendaList.querySelectorAll("[data-activity-id]");
            items.forEach((node) => {
                const activityId = node.dataset.activityId;

                const activityState = state.activeActivities?.[activityId] || null;
                const status = (
                    activityState?.status ||
                    (state.latestState?.currentActivity === activityId ? state.latestState?.status : null) ||
                    "stopped"
                ).toLowerCase();
                const isActive = status === "in_progress" || status === "paused" || state.latestState?.currentActivity === activityId;
                const isRunning = status === "in_progress";
                const isPaused = status === "paused";

                node.classList.toggle("is-active", isActive);
                node.classList.toggle("is-selected", Boolean(state.selectedActivityId) && state.selectedActivityId === activityId);
                node.classList.toggle("is-running", isRunning);
                node.classList.toggle("is-paused", isPaused);

                const chip = node.querySelector(".agenda-item-status");
                if (chip) {
                    let icon = "■";
                    let text = "Stopped";
                    if (isRunning) { icon = "▶"; text = "Running"; }
                    else if (isPaused) { icon = "⏸"; text = "Paused"; }
                    chip.textContent = `${icon} ${text}`;
                    chip.dataset.state = status;
                }
            });
        }

        function selectAgendaItem(activityId, { source = "user" } = {}) {
            if (!activityId) {
                return;
            }

            state.selectedActivityId = activityId;
            state.selectionMode = source === "user" ? "manual" : "auto";
            try {
                const url = new URL(window.location.href);
                url.searchParams.set("activity_id", activityId);
                window.history.replaceState(null, "", url.toString());
            } catch (error) {
                console.warn("Unable to persist activity selection in URL.", error);
            }

            highlightAgenda();
            updateActivityStatusIndicator();
            updateActivityPanels(state.latestState);

            if (state.isFacilitator) {
                renderActivityParticipantSection(activityId);
                loadActivityParticipantAssignment(activityId);
            }
        }

        function applyActiveActivity(activityId) {
            state.activeActivityId = activityId || null;
            // Auto-follow the active activity unless the user explicitly selected another
            if (!state.selectedActivityId || state.selectionMode === "auto") {
                state.selectedActivityId = activityId || state.selectedActivityId;
            }
            highlightAgenda();
            renderActivityParticipantSection(activityId);
        }

        function resolveParticipantModalActivityId() {
            return (
                activityParticipantState.currentActivityId ||
                state.selectedActivityId ||
                state.activeActivityId ||
                state.latestState?.currentActivity ||
                state.agenda?.[0]?.activity_id ||
                null
            );
        }

        function updateParticipantModalActivityMeta(activityId) {
            if (!ui.participantModalActivityMeta || !ui.participantModalActivityName || !ui.participantModalActivityType) {
                return;
            }
            if (!activityId) {
                ui.participantModalActivityMeta.hidden = true;
                ui.participantModalActivityName.textContent = "";
                ui.participantModalActivityType.textContent = "";
                return;
            }
            const activity =
                state.agendaMap.get(activityId) ||
                state.agenda?.find((item) => item.activity_id === activityId) ||
                null;
            const title = activity?.title || "Selected activity";
            const toolType = (activity?.tool_type || activity?.tool || "").toLowerCase();
            const moduleMeta = getModuleMeta(toolType);
            const toolLabel = moduleMeta?.label || activity?.tool_type || toolType || "Activity";

            ui.participantModalActivityName.textContent = title;
            ui.participantModalActivityType.textContent = toolLabel;
            ui.participantModalActivityMeta.hidden = false;
        }

        function setParticipantModalMode(mode) {
            if (!ui.participantAdminModal) {
                return;
            }
            const normalized = mode === "activity" ? "activity" : "meeting";
            if (ui.participantAdminPanel) {
                ui.participantAdminPanel.hidden = normalized !== "meeting";
            }
            if (ui.activityRosterPanel) {
                ui.activityRosterPanel.hidden = normalized !== "activity";
            }
            if (ui.participantModalTitle) {
                ui.participantModalTitle.textContent =
                    normalized === "activity" ? "Activity Participants" : "Manage Meeting Participants";
            }
            if (ui.participantModalTabs?.length) {
                ui.participantModalTabs.forEach((tab) => {
                    tab.dataset.active = tab.dataset.participantModalTab === normalized ? "true" : "";
                });
            }
            if (normalized === "meeting") {
                updateParticipantModalActivityMeta(null);
                renderMeetingSelectedList();
                renderMeetingDirectory();
            } else if (normalized === "activity") {
                const activityId = resolveParticipantModalActivityId();
                activityParticipantState.currentActivityId = activityId;
                updateParticipantModalActivityMeta(activityId);
                renderActivityParticipantSection(activityId);
                if (activityId) {
                    loadActivityParticipantAssignment(activityId);
                }
            }
        }

        function openActivityParticipantModal(activityId) {
            if (!ui.participantAdminModal) {
                console.error("Participant modal not found in DOM");
                return;
            }
            ui.participantAdminModal.hidden = false;
            activityParticipantState.currentActivityId = activityId;
            activityParticipantState.availableHighlighted.clear();
            activityParticipantState.selectedHighlighted.clear();
            activityParticipantState.dirty = false;
            activityParticipantState.loading = false;
            activityParticipantState.lastLoadFailed = false;
            setParticipantModalMode("activity");
            loadActivityParticipantAssignment(activityId, { force: true });
            // Bind close
            if (ui.closeParticipantAdminModal) {
                ui.closeParticipantAdminModal.onclick = () => {
                    ui.participantAdminModal.hidden = true;
                };
            }
        }

        function openParticipantAdminModal() {
            if (!ui.participantAdminModal) return;
            setParticipantModalMode("meeting");
            ui.participantAdminModal.hidden = false;
            // Bind close
            if (ui.closeParticipantAdminModal) {
                ui.closeParticipantAdminModal.onclick = () => {
                    ui.participantAdminModal.hidden = true;
                };
            }
        }

        function updateFacilitatorControls() {
            // Minimal update: check if we need to init directory
            if (state.isFacilitator && !participantDirectoryInitialized && ui.facilitatorControls.meetingDirectoryList) {
                participantDirectoryInitialized = true;
                loadParticipantDirectory({ resetPage: true });
            }
            // Other global facilitator logic if any
        }

        function formatTimestamp(isoString) {
            if (!isoString) return "—";
            try {
                const date = new Date(isoString);
                if (isNaN(date.getTime())) return "—";
                return date.toLocaleTimeString(undefined, {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                });
            } catch (e) {
                return "—";
            }
        }



        function showActiveToolPanel(toolType, activity, { isActive = true } = {}) {
            if (!ui.genericPanel.root) {
                return;
            }
            const useGeneric = Boolean(toolType) && !["brainstorming", "voting", "categorization"].includes(toolType);
            if (!useGeneric) {
                ui.genericPanel.root.hidden = true;
                return;
            }

            const moduleMeta = getModuleMeta(toolType) || { label: toolType };
            ui.genericPanel.root.hidden = false;
            ui.genericPanel.title.textContent = activity?.title || moduleMeta.label || "Active Activity";
            const instructions = (activity?.instructions || "").trim();
            ui.genericPanel.description.textContent =
                instructions ||
                (isActive
                    ? `The ${moduleMeta.label || toolType} activity is active. Follow facilitator guidance.`
                    : `This ${moduleMeta.label || toolType} activity is closed. Review details with your facilitator.`);
        }

        function updateActivityPanels(snapshot) {
            const eligibility = resolveSelectedActivityContext(snapshot);
            const toolType = (eligibility?.toolType || "").toLowerCase();
            const activeActivity = eligibility?.activity;
            const instructions = (activeActivity?.instructions || "").trim();
            const activityConfig = activeActivity?.config || {};
            const prompt = (activityConfig.prompt || "").trim();
            const isActive = Boolean(eligibility?.isActive);
            const canEnter = Boolean(eligibility?.accessState?.canEnter);
            const hasTool = Boolean(eligibility?.activityId && toolType);
            const showTool = Boolean(hasTool && canEnter && (isActive || state.isFacilitator));
            let showBrainstorming = showTool && toolType === "brainstorming";
            let showVoting = showTool && toolType === "voting";
            let showCategorization = showTool && toolType === "categorization";
            const showTransfer = transferState.active && state.isFacilitator;
            if (showTransfer) {
                showBrainstorming = false;
                showVoting = false;
                showCategorization = false;
            }

            updateParticipantStatus(eligibility);
            state.participantRestricted = Boolean(eligibility?.restricted);
            if (!state.isFacilitator) {
                if (state.selectedActivityId && eligibility && !eligibility.accessState?.canEnter) {
                    showAccessMessage(eligibility.accessState?.title || "You do not have access to this activity.");
                } else {
                    showAccessMessage("");
                }
            }

            if (brainstorming.root) {
                brainstorming.root.hidden = !showBrainstorming;
                if (showBrainstorming) {
                    // Detect activity change and clear ideas if switching to different activity
                    const newActivityId = eligibility?.activityId || null;
                    if (brainstormingActivityId !== newActivityId) {
                        brainstormingActivityId = newActivityId;
                        brainstormingIdeasLoaded = false;
                        brainstormingIdeaIds.clear();
                        resetBrainstormingIdeas();
                    }
                    activeBrainstormingConfig = activityConfig || {};
                    brainstormingActive = Boolean(isActive && canEnter);
                    if (brainstorming.title) {
                        const activityTitle = activeActivity?.title || "Brainstorming";
                        brainstorming.title.textContent = `${activityTitle} - BRAINSTORMING`;
                    }
                    if (brainstorming.description) {
                        brainstorming.description.textContent =
                            instructions ||
                            prompt ||
                            (isActive
                                ? "Brainstorming is live. Share your ideas with the group."
                                : "This brainstorming activity is closed. Review the ideas below.");
                    }
                    setBrainstormingFormEnabled(Boolean(isActive && canEnter), activityConfig);
                    ensureReplyButtons();
                    loadBrainstormingIdeas(newActivityId, activityConfig);
                    setBrainstormingError(null);
                } else {
                    const waitingCopy = !hasTool
                        ? "The facilitator will open the brainstorming board when ready."
                        : eligibility?.restricted
                            ? "You're not in this brainstorming round. We'll bring you in when it is your turn."
                            : state.isFacilitator
                                ? "This brainstorming activity is closed. Select another agenda item to continue."
                                : "The facilitator will open the brainstorming board when ready.";
                    activeBrainstormingConfig = {};
                    if (brainstorming.title) {
                        const activityTitle = activeActivity?.title || "Brainstorming";
                        brainstorming.title.textContent = `${activityTitle} - BRAINSTORMING`;
                    }
                    if (brainstorming.description) {
                        brainstorming.description.textContent = waitingCopy;
                    }
                    setBrainstormingFormEnabled(false);
                    brainstormingIdeasLoaded = false;
                    brainstormingActivityId = null;
                    setBrainstormingError(null);
                    brainstormingActive = false;
                    ensureReplyButtons();
                }
            }

            if (voting.root) {
                voting.root.hidden = !showVoting;
                if (showVoting) {
                    activeVotingConfig = activityConfig || {};
                    votingTiming.begin(eligibility?.activityId, "panel_visible");
                    votingTiming.mark("panel_visible", {
                        is_active: Boolean(isActive),
                        can_enter: Boolean(canEnter),
                    });
                    if (voting.instructions) {
                        voting.instructions.textContent =
                            instructions ||
                            (isActive
                                ? "Cast your votes for the options below."
                                : "This voting activity is closed. Review the results below.");
                    }
                    // Facilitators can adjust votes even when the activity is not currently running.
                    // Use authoritative backend status if available, fallback to snapshot
                    votingIsActive = Boolean(canEnter && (votingSummary?.is_active ?? isActive));
                    const expectedActiveState = Boolean(canEnter && isActive);
                    const knownSummaryActive =
                        votingSummary?.is_active !== undefined
                            ? Boolean(votingSummary.is_active)
                            : null;
                    const activeStateChanged =
                        knownSummaryActive !== null && knownSummaryActive !== expectedActiveState;
                    if (votingActivityId !== eligibility?.activityId || !votingSummary || activeStateChanged) {
                        if (activeStateChanged) {
                            votingTiming.mark("active_state_changed_refresh", {
                                summary_is_active: knownSummaryActive,
                                expected_is_active: expectedActiveState,
                            });
                        }
                        loadVotingOptions(eligibility?.activityId, activityConfig);
                    }
                    updateVotingFooter(votingSummary);
                } else {
                    const waitingCopy = !hasTool
                        ? "The facilitator will open voting when ready."
                        : eligibility?.restricted
                            ? "You're not assigned to this voting round. Please wait for the next activity."
                            : state.isFacilitator
                                ? "This voting activity is closed. Select another agenda item to continue."
                                : "The facilitator will open voting when ready.";
                    votingSummary = null;
                    votingActivityId = null;
                    votingIsActive = false;
                    activeVotingConfig = {};
                    syncVotingDraftFromSummary(null);
                    setVotingError(null);
                    setVotingStatus("");
                    if (voting.instructions) {
                        voting.instructions.textContent = waitingCopy;
                    }
                    if (voting.notice) {
                        voting.notice.textContent = "";
                    }
                    updateVotingFooter(null);
                }
            }

            if (categorization.root) {
                categorization.root.hidden = !showCategorization;
                if (showCategorization) {
                    activeCategorizationConfig = activityConfig || {};
                    categorizationIsActive = Boolean(isActive && canEnter);
                    const newActivityId = eligibility?.activityId || null;
                    if (categorizationActivityId !== newActivityId) {
                        categorizationActivityId = newActivityId;
                        categorizationSelectedBucketId = "UNSORTED";
                        categorizationSelectedItemKey = null;
                    }
                    if (categorization.instructions) {
                        categorization.instructions.textContent =
                            instructions ||
                            (isActive
                                ? "Categorization is live. Place ideas into the best buckets."
                                : "This categorization activity is closed.");
                    }
                    loadCategorizationState(newActivityId, activeCategorizationConfig, { force: true });
                } else {
                    activeCategorizationConfig = {};
                    categorizationIsActive = false;
                    categorizationActivityId = null;
                    categorizationSelectedBucketId = null;
                    categorizationSelectedItemKey = null;
                    renderCategorizationSummary(null);
                    setCategorizationError(null);
                }
            }

            if (transfer.root) {
                transfer.root.hidden = !showTransfer;
                if (showTransfer) {
                    if (transfer.targetToolType && transfer.targetToolType.options.length === 0) {
                        buildTransferTargetOptions();
                    }
                    if (transferState.donorActivityId && !transferState.loadAttempted && !transferState.loading) {
                        loadTransferBundles();
                    }
                    setTransferButtonsState();
                }
            }

            const showGeneric = showTool && !showBrainstorming && !showVoting && !showCategorization && !showTransfer && toolType;
            showActiveToolPanel(
                showGeneric ? toolType : null,
                showGeneric ? activeActivity : null,
                { isActive },
            );
            updateSubmitButtonState();
        }



        function moveSelection(offset) {
            if (state.agenda.length === 0) {
                return;
            }
            const currentId = state.selectedActivityId || state.activeActivityId;
            let currentIndex = state.agenda.findIndex((item) => item.activity_id === currentId);
            if (currentIndex === -1) {
                currentIndex = 0;
            }
            let nextIndex = currentIndex + offset;
            if (nextIndex < 0) {
                nextIndex = 0;
            } else if (nextIndex >= state.agenda.length) {
                nextIndex = state.agenda.length - 1;
            }
            const nextActivity = state.agenda[nextIndex];
            if (nextActivity) {
                selectAgendaItem(nextActivity.activity_id, { source: "user" });
            }
        }

        function setFacilitatorFeedback(message, variant = "info") {
            if (!ui.facilitatorControls.feedback) {
                return;
            }
            if (!message) {
                ui.facilitatorControls.feedback.textContent = "";
                ui.facilitatorControls.feedback.dataset.variant = "";
                return;
            }
            ui.facilitatorControls.feedback.textContent = message;
            ui.facilitatorControls.feedback.dataset.variant = variant;
        }

        async function sendControl(action, { tool, activityId } = {}) {
            if (!state.isFacilitator || state.facilitatorBusy) {
                return;
            }
            setFacilitatorFeedback("", "info");
            state.facilitatorBusy = true;
            updateFacilitatorControls();
            try {
                const payload = { action };
                if (tool) {
                    payload.tool = tool;
                }
                if (activityId) {
                    payload.activityId = activityId;
                    const assignment = state.activityAssignments.get(activityId);
                    if (assignment) {
                        payload.metadata = payload.metadata || {};
                        payload.metadata.participantScope = assignment.mode;
                        if (assignment.mode === "custom") {
                            payload.metadata.participantIds = assignment.participant_ids || [];
                        }
                    }
                }

                // Add timer state to payload
                if (action === "start_tool" || action === "stop_tool") {
                    payload.metadata = payload.metadata || {};
                    payload.metadata.elapsedTime = state.elapsedTime;
                }
                if (action === "start_tool") {
                    payload.status = "in_progress";
                } else if (action === "stop_tool") {
                    payload.status = "completed"; // Or a new "stopped" status
                }

                const response = await fetch(
                    `/api/meetings/${encodeURIComponent(context.meetingId)}/control`,
                    {
                        method: "POST",
                        credentials: "include",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify(payload),
                    },
                );
                if (!response.ok) {
                    const data = await response.json().catch(() => ({}));
                    if (response.status === 409) {
                        const conflictDetailsHeader = response.headers.get("X-Conflict-Details");
                        let conflictDetails = null;
                        if (conflictDetailsHeader) {
                            try {
                                conflictDetails = JSON.parse(conflictDetailsHeader);
                            } catch (e) {
                                console.error("Failed to parse X-Conflict-Details header:", e);
                            }
                        }
                        if (!conflictDetails && data && typeof data === "object") {
                            conflictDetails =
                                data.conflict_details ||
                                data.conflictDetails ||
                                null;
                        }
                        const errorMessage = typeof data.detail === "string" ? data.detail : "An unknown conflict occurred.";
                        // Propagate the conflict information up
                        const error = new Error(errorMessage);
                        error.isConflict = true;
                        error.conflictDetails = conflictDetails;
                        throw error;
                    }
                    throw new Error(
                        typeof data.detail === "string" ? data.detail : "Unable to apply activity change.",
                    );
                }
                const responseBody = await response.json().catch(() => ({}));
                const actionLabel =
                    action === "start_tool"
                        ? "Activity started."
                        : action === "stop_tool"
                            ? "Activity stopped and reset."
                            : "Activity control requested.";

                // Apply returned state immediately (in addition to websocket broadcast) so UI updates even if WS lags.
                if (responseBody && responseBody.state) {
                    handleStateSnapshot(responseBody.state, true);
                }
                const requestedTool = String(
                    tool ||
                        state.agendaMap.get(activityId || "")?.tool_type ||
                        "",
                ).toLowerCase();
                if (
                    activityId &&
                    requestedTool === "voting" &&
                    (action === "start_tool" || action === "resume_tool")
                ) {
                    votingTiming.mark("control_forced_refresh", { action, activity_id: activityId });
                    loadVotingOptions(activityId, state.agendaMap.get(activityId)?.config || activeVotingConfig || {});
                }
                setFacilitatorFeedback(actionLabel, "success");
            } catch (error) {
                console.error("Facilitator control failed:", error);
                setFacilitatorFeedback(error.message || "Unable to update the activity.", "error");
                throw error; // Propagate error so callers can handle it (e.g. showCollisionModal)
            } finally {
                state.facilitatorBusy = false;
                updateFacilitatorControls();
            }
        }

        function handleStateSnapshot(snapshot, emitLog = false) {
            if (!snapshot) {
                state.latestState = null;
                state.activeActivities = {};
                renderState(null);
                applyActiveActivity(null);
                updateActivityPanels(null);
                stopTimer(); // Stop timer when state is cleared
                if (emitLog) {
                    logEvent("Meeting state cleared.");
                }
                return;
            }

            const activeActivities = {};
            if (snapshot.activeActivities) {
                const entries = Array.isArray(snapshot.activeActivities)
                    ? snapshot.activeActivities
                    : Object.values(snapshot.activeActivities);
                entries.forEach((entry) => {
                    if (!entry || typeof entry !== "object") return;
                    const id = entry.activityId || entry.activity_id;
                    if (!id) return;
                    activeActivities[id] = entry;
                });
            }

            state.latestState = {
                status: snapshot.status ?? state.latestState?.status ?? null,
                currentActivity: snapshot.currentActivity ?? snapshot.agendaItemId ?? null,
                currentTool: snapshot.currentTool ?? null,
                agendaItemId: snapshot.agendaItemId ?? null,
                metadata: snapshot.metadata || {},
                participants: Array.isArray(snapshot.participants) ? snapshot.participants : [],
                agenda: Array.isArray(snapshot.agenda) ? snapshot.agenda : state.latestState?.agenda || [],
                updatedAt: snapshot.updatedAt || new Date().toISOString(),
            };
            state.activeActivities = activeActivities;

            const currentActivityId = state.latestState.currentActivity;
            const scopeFromMetadata = (state.latestState.metadata?.participantScope || state.latestState.metadata?.participant_scope || "").toLowerCase();
            const metaIds = Array.isArray(state.latestState.metadata?.participantIds || state.latestState.metadata?.participant_ids)
                ? (state.latestState.metadata.participantIds || state.latestState.metadata.participant_ids).map((id) => String(id)).filter(Boolean)
                : [];
            if (currentActivityId && state.activityAssignments.has(currentActivityId)) {
                const existingAssignment = state.activityAssignments.get(currentActivityId);
                const updatedAssignment = {
                    ...existingAssignment,
                    mode: scopeFromMetadata === "custom" ? "custom" : "all",
                    participant_ids: scopeFromMetadata === "custom" ? metaIds : [],
                };
                state.activityAssignments.set(currentActivityId, updatedAssignment);
                if (state.isFacilitator && state.selectedActivityId === currentActivityId) {
                    renderActivityParticipantSection(currentActivityId);
                }
            }

            // Update timer state based on snapshot
            const currentActivity = state.latestState.currentActivity
                ? state.agendaMap.get(state.latestState.currentActivity)
                : null;
            if (currentActivity) {
                state.elapsedTime = state.latestState.metadata.elapsedTime ?? currentActivity.elapsed_duration ?? 0;
            } else {
                state.elapsedTime = 0;
            }

            if (state.latestState.status === "in_progress" && state.latestState.currentActivity) {
                startTimer();
            } else if (state.latestState.status === "paused" && state.latestState.currentActivity) {
                pauseTimer();
            } else {
                stopTimer();
            }

            renderState(state.latestState);
            renderAgenda(state.latestState.agenda); // Call renderAgenda here
            applyActiveActivity(state.latestState.currentActivity);
            updateActivityPanels(state.latestState);
            updateActivityStatusIndicator();
            updateAgendaSummary();

            if (emitLog) {
                const activityLabel = state.latestState.currentActivity || "unknown activity";
                const toolLabel = state.latestState.currentTool ? ` tool ${state.latestState.currentTool}` : "";
                logEvent(`Meeting state updated: ${activityLabel}${toolLabel}`);
            }
        }

        function handleRealtimeMessage(message) {
            const { type, payload } = message;
            switch (type) {
                case "connection_ack":
                    setStatus("Connected", "success");
                    if (Array.isArray(payload?.participants)) {
                        payload.participants.forEach((participant) => {
                            upsertParticipant(participant.connectionId, participant);
                        });
                    }
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent("Connected to meeting.");
                    break;
                case "participant_joined":
                    upsertParticipant(payload?.connectionId, payload);
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent(`Participant joined: ${payload?.userId || payload?.connectionId}`);
                    break;
                case "participant_left":
                    removeParticipant(payload?.connectionId);
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent(`Participant left: ${payload?.userId || payload?.connectionId}`);
                    break;
                case "participant_identified":
                    upsertParticipant(payload?.connectionId, payload);
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent(`Participant identified: ${payload?.userId || payload?.connectionId}`);
                    break;
                case "pong":
                    logEvent("Heartbeat acknowledged.");
                    break;
                case "meeting_state":
                    // If it's a full meeting state snapshot, update everything
                    handleStateSnapshot(payload, true);
                    break;
                case "agenda_update":
                    // If it's an agenda-specific update, only re-render the agenda
                    if (Array.isArray(payload)) { // Payload for agenda_update is just the list of agenda items
                        state.agenda = payload.sort((a, b) => (a.order_index || 0) - (b.order_index || 0));
                        state.agendaMap = new Map(state.agenda.map((item) => [item.activity_id, item]));
                        renderAgenda(state.agenda);
                        logEvent("Agenda updated in real-time.");
                    }
                    break;
                case "voting_update":
                    if (payload && votingActivityId === payload.activity_id) {
                        loadVotingOptions(payload.activity_id);
                    }
                    break;
                case "categorization_update":
                    if (payload && categorizationActivityId === payload.activity_id) {
                        loadCategorizationState(payload.activity_id, activeCategorizationConfig, { force: true });
                    }
                    break;
                case "new_idea":
                    handleIncomingIdea(payload);
                    break;
                case "transfer_count_update":
                    if (payload?.activity_id) {
                        updateTransferCountForActivity(
                            payload.activity_id,
                            Number.isFinite(Number(payload.delta)) ? Number(payload.delta) : 0,
                        );
                    }
                    break;
                default:
                    logEvent(`Event received: ${type}`);
                    break;
            }
        }

        function updateActivityStatusIndicator() {
            const badge = ui.facilitatorControls.statusBadge;
            if (!badge) return;
            const selectedId = state.selectedActivityId || state.activeActivityId;
            const entry = selectedId ? state.activeActivities[selectedId] : null;
            if (entry) {
                badge.textContent = "Running";
                badge.classList.remove("status-stopped");
                badge.classList.add("status-running");
            } else {
                badge.textContent = "Stopped";
                badge.classList.remove("status-running");
                badge.classList.add("status-stopped");
            }
        }

        async function loadModuleCatalog() {
            try {
                const response = await fetch("/api/meetings/modules", { credentials: "include" });
                if (response.ok) {
                    const data = await response.json();
                    if (Array.isArray(data) && data.length > 0) {
                        state.moduleCatalog = data;
                    } else {
                        state.moduleCatalog = [...DEFAULT_MODULES];
                    }
                } else {
                    state.moduleCatalog = [...DEFAULT_MODULES];
                }
            } catch (error) {
                console.warn("Unable to load module catalog, falling back to defaults.", error);
                state.moduleCatalog = [...DEFAULT_MODULES];
            }
            state.moduleMap = new Map(
                state.moduleCatalog.map((entry) => [entry.tool_type.toLowerCase(), entry]),
            );
        }

        async function loadMeetingDetails() {
            const response = await fetch(`/api/meetings/${encodeURIComponent(context.meetingId)}`, {
                credentials: "include",
            });
            if (!response.ok) {
                const data = await response.json().catch(() => ({}));
                throw new Error(
                    typeof data.detail === "string" ? data.detail : "Unable to load meeting details.",
                );
            }

            const meeting = await response.json();
            state.meeting = meeting;
            document.title = `${meeting.title} – Meeting`;

            const facilitatorIds = new Set(
                (meeting.facilitator_user_ids || []).concat(meeting.owner_id ? [meeting.owner_id] : []),
            );
            const participantIds = new Set(meeting.participant_ids || []);

            state.isFacilitator =
                facilitatorIds.has(context.userId) || isAdminUser;
            state.isParticipant = state.isFacilitator || participantIds.has(context.userId);

            if (!state.isParticipant) {
                throw new Error("You are not registered for this meeting.");
            }
            if (root) {
                root.dataset.viewMode = state.isFacilitator ? "facilitator" : "participant";
            }

            renderAgenda(meeting.agenda || []);
            updateAgendaSummary();

            state.selectedActivityId = null;
            state.activeActivityId = null;
            state.selectionMode = "auto";
            if (!state.requestedActivityId) {
                state.requestedActivityId = new URLSearchParams(window.location.search).get("activity_id");
            }
            if (!state.requestedActivityId) {
                const storedId = localStorage.getItem(`transfer:lastActivity:${context.meetingId}`);
                if (storedId) {
                    state.requestedActivityId = storedId;
                }
            }
            if (state.requestedActivityId && state.agendaMap.has(state.requestedActivityId)) {
                selectAgendaItem(state.requestedActivityId, { source: "user" });
                localStorage.removeItem(`transfer:lastActivity:${context.meetingId}`);
                state.requestedActivityId = null;
            }

            renderParticipants();
            updateParticipantStatus(resolveSelectedActivityContext(state.latestState));
            if (state.isFacilitator) {
                await loadAssignedParticipants();
            }
        }

        function enforceMeetingAccess(meeting) {
            if (!meeting || typeof meeting !== "object") {
                return false;
            }
            const facilitatorIds = new Set(
                (meeting.facilitator_user_ids || []).concat(meeting.owner_id ? [meeting.owner_id] : []),
            );
            const participantIds = new Set(meeting.participant_ids || []);

            const isFacilitator = facilitatorIds.has(context.userId) || isAdminUser;
            const isParticipant = isFacilitator || participantIds.has(context.userId);

            state.isFacilitator = isFacilitator;
            state.isParticipant = isParticipant;

            if (!isParticipant) {
                showAccessMessage("Your access to this meeting has been revoked.");
                setStatus("Access revoked", "error");
                setTimeout(() => {
                    window.location.href = "/dashboard";
                }, 800);
                return false;
            }
            return true;
        }

        async function refreshMeetingDetails() {
            if (meetingRefreshInFlight || !meetingRefreshConfig.enabled) {
                return;
            }
            meetingRefreshInFlight = true;
            try {
                const response = await fetch(`/api/meetings/${encodeURIComponent(context.meetingId)}`, {
                    credentials: "include",
                    cache: "no-store",
                });
                if (!response.ok) {
                    throw new Error("Unable to refresh meeting details.");
                }
                const meeting = await response.json();
                state.meeting = meeting;
                document.title = `${meeting.title} – Meeting`;
                if (!enforceMeetingAccess(meeting)) {
                    return;
                }
                renderAgenda(meeting.agenda || []);
                updateAgendaSummary();
                renderParticipants();
                updateParticipantStatus(resolveSelectedActivityContext(state.latestState));

                try {
                    const stateResponse = await fetch(
                        `/api/meetings/${encodeURIComponent(context.meetingId)}/state`,
                        { credentials: "include", cache: "no-store" },
                    );
                if (stateResponse.ok) {
                    const snapshot = await stateResponse.json().catch(() => null);
                    if (snapshot && snapshot.meetingId) {
                        handleStateSnapshot(snapshot, false);
                        if (state.latestState) {
                                state.latestState.agenda = Array.isArray(meeting.agenda)
                                    ? meeting.agenda
                                    : state.latestState.agenda;
                            }
                        }
                    }
                } catch (error) {
                    console.warn("Meeting state refresh failed:", error);
                }
                if (voting.root && !voting.root.hidden && votingActivityId) {
                    loadVotingOptions(votingActivityId, activeVotingConfig);
                }
                meetingRefreshFailures = 0;
            } catch (error) {
                meetingRefreshFailures += 1;
                console.warn("Meeting refresh failed:", error);
            } finally {
                meetingRefreshInFlight = false;
                startMeetingRefresh();
            }
        }

        function getMeetingRefreshDelayMs() {
            if (meetingRefreshFailures > 0) {
                return meetingRefreshConfig.failureBackoffMs;
            }
            return document.hidden
                ? meetingRefreshConfig.hiddenIntervalMs
                : meetingRefreshConfig.intervalMs;
        }

        function stopMeetingRefresh() {
            if (meetingRefreshTimer) {
                clearTimeout(meetingRefreshTimer);
                meetingRefreshTimer = null;
            }
        }

        function startMeetingRefresh() {
            if (!meetingRefreshConfig.enabled) {
                return;
            }
            stopMeetingRefresh();
            meetingRefreshTimer = setTimeout(() => {
                refreshMeetingDetails();
            }, getMeetingRefreshDelayMs());
        }

        function connectRealtime() {
            if (!realtimeAvailable) {
                setStatus("Realtime unavailable", "warning");
                startMeetingRefresh();
                return;
            }
            meetingSocket = window.DecideroRealtime.createMeetingSocket({
                meetingId: context.meetingId,
                clientId: context.userId || undefined,
                onOpen: () => {
                    setStatus("Connected", "success");
                    realtimeConnected = true;
                    startMeetingRefresh();
                    if (context.userId) {
                        meetingSocket.send("identify", { userId: context.userId });
                    }
                    meetingSocket.send("state_request");
                },
                onClose: () => {
                    setStatus("Disconnected", "warning");
                    realtimeConnected = false;
                    startMeetingRefresh();
                    handleStateSnapshot(null, true);
                },
                onError: () => {
                    setStatus("Error", "error");
                    realtimeConnected = false;
                    startMeetingRefresh();
                },
                onMessage: (message) => handleRealtimeMessage(message),
            });

            if (heartbeatTimer) {
                clearInterval(heartbeatTimer);
            }
            heartbeatTimer = setInterval(() => {
                if (!meetingSocket || !meetingSocket.send("ping")) {
                    clearInterval(heartbeatTimer);
                }
            }, 25000);
        }

        function handleIncomingIdea(rawIdea) {
            if (!rawIdea) {
                return;
            }
            const ideaActivityId = rawIdea.activity_id || rawIdea.activityId || null;
            if (!brainstormingActivityId || ideaActivityId !== brainstormingActivityId) {
                return;
            }
            brainstormingIdeasLoaded = true;
            if (rawIdea.parent_id) {
                appendSubcomment(rawIdea);
            } else {
                appendIdea(rawIdea, { prepend: false });
            }
            logEvent("New brainstorming idea received.");
        }

        if (ui.agendaCollapseToggle) {
            const stored = (() => {
                try {
                    return window.localStorage.getItem("agendaCollapsed");
                } catch (error) {
                    return null;
                }
            })();
            if (stored === "1") {
                setAgendaCollapsed(true, { persist: false });
            }
            ui.agendaCollapseToggle.addEventListener("click", () => {
                const isCollapsed = ui.agendaCard?.classList.contains("is-collapsed");
                setAgendaCollapsed(!isCollapsed);
            });
        }

        if (ui.facilitatorControls.prev) {
            ui.facilitatorControls.prev.addEventListener("click", () => moveSelection(-1));
        }
        if (ui.facilitatorControls.next) {
            ui.facilitatorControls.next.addEventListener("click", () => moveSelection(1));
        }

        if (brainstorming.autoJumpToggle) {
            brainstorming.autoJumpToggle.addEventListener("change", () => {
                localStorage.setItem(
                    getBrainstormingAutoJumpStorageKey(),
                    brainstorming.autoJumpToggle.checked ? "true" : "false",
                );
            });
            syncBrainstormingAutoJumpToggle();
        }

        if (brainstorming.form) {
            const handleBrainstormingSubmit = () => {
                if (!brainstormingActive || brainstormingSubmitInFlight) {
                    return;
                }
                const content = (brainstorming.textarea && brainstorming.textarea.value) || "";
                const trimmed = content.trim();
                if (!trimmed) {
                    setBrainstormingError("Please share an idea before submitting.");
                    return;
                }
                submitIdea(trimmed);
            };

            brainstorming.form.addEventListener("input", () => {
                if (!brainstormingActive) {
                    setBrainstormingFormEnabled(false);
                    return;
                }
                const content = (brainstorming.textarea && brainstorming.textarea.value) || "";
                const trimmed = content.trim();
                const maxLength =
                    activeBrainstormingConfig.idea_character_limit || brainstormingLimits.ideaCharacterLimit;
                const ready = trimmed.length > 0 && (!maxLength || trimmed.length <= maxLength);
                if (brainstorming.submit) {
                    brainstorming.submit.disabled = !ready || brainstormingSubmitInFlight;
                }
            });

            if (brainstorming.textarea) {
                brainstorming.textarea.addEventListener("keydown", (event) => {
                    if (event.isComposing || event.key !== "Enter" || event.shiftKey) {
                        return;
                    }
                    event.preventDefault();
                    handleBrainstormingSubmit();
                });
            }

            brainstorming.form.addEventListener("submit", (event) => {
                event.preventDefault();
                handleBrainstormingSubmit();
            });
        }

        if (voting.submit) {
            voting.submit.addEventListener("click", () => {
                submitVotingDraft();
            });
        }

        window.addEventListener("decidero:voting-timing-update", () => {
            renderVotingTimingDebug();
        });
        let lastVotingTimingActivityLog = null;
        window.addEventListener("decidero:voting-timing-session", (event) => {
            const detail = event?.detail || {};
            const marks = detail.marks || {};
            const activityId = detail.activity_id || "unknown";
            const signature = `${activityId}:${detail.total_ms ?? "na"}:${detail.status || "unknown"}`;
            if (signature === lastVotingTimingActivityLog) {
                return;
            }
            lastVotingTimingActivityLog = signature;
            const responseMs = marks.response_received ?? null;
            const parsedMs = marks.response_parsed ?? null;
            const renderMs = marks.render_complete ?? null;
            const interactiveMs = marks.interactive_ready ?? null;
            const status = detail.status || "unknown";
            const total = detail.total_ms ?? "--";
            logEvent(
                `Voting timing ${activityId}: total=${total}ms interactive=${interactiveMs ?? "--"}ms response=${responseMs ?? "--"}ms parsed=${parsedMs ?? "--"}ms render=${renderMs ?? "--"}ms status=${status}`,
            );
        });
        renderVotingTimingDebug();

        if (voting.list) {
            voting.list.addEventListener("click", handleVotingDotClick);
        }

        if (voting.reset) {
            voting.reset.addEventListener("click", () => {
                resetVotingDraft(votingSummary);
            });
        }

        if (voting.viewResultsButton) {
            voting.viewResultsButton.addEventListener("click", () => {
                openVotingResultsModal();
            });
        }

        if (voting.closeResultsModal) {
            voting.closeResultsModal.addEventListener("click", () => {
                closeVotingResultsModal();
            });
        }

        if (voting.resultsModal) {
            voting.resultsModal.addEventListener("click", (event) => {
                if (event.target === voting.resultsModal) {
                    closeVotingResultsModal();
                }
            });
        }

        if (categorization.refresh) {
            categorization.refresh.addEventListener("click", () => {
                if (categorizationActivityId) {
                    loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                }
            });
        }

        if (categorization.addBucket) {
            categorization.addBucket.addEventListener("click", async () => {
                if (!categorizationActivityId) {
                    return;
                }
                const title = window.prompt("Bucket title");
                if (!title || !title.trim()) {
                    return;
                }
                try {
                    const response = await fetch(
                        `/api/meetings/${encodeURIComponent(context.meetingId)}/categorization/buckets`,
                        {
                            method: "POST",
                            credentials: "include",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                activity_id: categorizationActivityId,
                                title: title.trim(),
                            }),
                        },
                    );
                    if (!response.ok) {
                        const err = await response.json().catch(() => ({}));
                        throw new Error(err.detail || "Unable to add bucket.");
                    }
                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                } catch (error) {
                    setCategorizationError(error.message || "Unable to add bucket.");
                }
            });
        }

        if (categorization.addItem) {
            categorization.addItem.addEventListener("click", async () => {
                if (!categorizationActivityId) {
                    return;
                }
                const content = window.prompt("Idea text");
                if (!content || !content.trim()) {
                    return;
                }
                try {
                    const created = await createCategorizationItem(categorizationActivityId, content.trim());
                    categorizationSelectedItemKey = String(created?.item_key || "") || null;
                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                } catch (error) {
                    setCategorizationError(error.message || "Unable to add idea.");
                }
            });
        }

        if (categorization.editItem) {
            categorization.editItem.addEventListener("click", async () => {
                if (!categorizationActivityId || !categorizationSelectedItemKey) {
                    return;
                }
                const selected = (categorizationState?.items || []).find(
                    (item) => String(item.item_key || "") === String(categorizationSelectedItemKey),
                );
                if (!selected) {
                    return;
                }
                try {
                    await renameCategorizationItem(
                        categorizationActivityId,
                        categorizationSelectedItemKey,
                        selected?.content || "",
                    );
                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                } catch (error) {
                    setCategorizationError(error.message || "Unable to edit idea.");
                }
            });
        }

        if (categorization.deleteItem) {
            categorization.deleteItem.addEventListener("click", async () => {
                if (!categorizationActivityId || !categorizationSelectedItemKey) {
                    return;
                }
                const selected = (categorizationState?.items || []).find(
                    (item) => String(item.item_key || "") === String(categorizationSelectedItemKey),
                );
                if (!selected) {
                    return;
                }
                try {
                    await deleteCategorizationItem(
                        categorizationActivityId,
                        categorizationSelectedItemKey,
                        selected?.content || "",
                    );
                    categorizationSelectedItemKey = null;
                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                } catch (error) {
                    setCategorizationError(error.message || "Unable to delete idea.");
                }
            });
        }

        if (categorization.editBucket) {
            categorization.editBucket.addEventListener("click", async () => {
                if (!categorizationActivityId || !categorizationSelectedBucketId || categorizationSelectedBucketId === "UNSORTED") {
                    return;
                }
                const selected = (categorizationState?.buckets || []).find(
                    (bucket) => String(bucket.category_id || "") === String(categorizationSelectedBucketId),
                );
                try {
                    await renameCategorizationBucket(
                        categorizationActivityId,
                        categorizationSelectedBucketId,
                        selected?.title || categorizationSelectedBucketId,
                    );
                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                } catch (error) {
                    setCategorizationError(error.message || "Unable to edit bucket.");
                }
            });
        }

        if (categorization.deleteBucket) {
            categorization.deleteBucket.addEventListener("click", async () => {
                if (!categorizationActivityId || !categorizationSelectedBucketId || categorizationSelectedBucketId === "UNSORTED") {
                    return;
                }
                const selected = (categorizationState?.buckets || []).find(
                    (bucket) => String(bucket.category_id || "") === String(categorizationSelectedBucketId),
                );
                try {
                    await deleteCategorizationBucket(
                        categorizationActivityId,
                        categorizationSelectedBucketId,
                        selected?.title || categorizationSelectedBucketId,
                    );
                    categorizationSelectedBucketId = "UNSORTED";
                    await loadCategorizationState(categorizationActivityId, activeCategorizationConfig, { force: true });
                } catch (error) {
                    setCategorizationError(error.message || "Unable to delete bucket.");
                }
            });
        }


        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && voting.resultsModal && !voting.resultsModal.hidden) {
                closeVotingResultsModal();
            }
        });

        window.addEventListener("beforeunload", () => {
            if (heartbeatTimer) {
                clearInterval(heartbeatTimer);
            }
            if (meetingRefreshTimer) {
                clearTimeout(meetingRefreshTimer);
            }
            if (meetingSocket) {
                meetingSocket.close();
            }
        });

        document.addEventListener("visibilitychange", () => {
            if (meetingRefreshConfig.enabled) {
                startMeetingRefresh();
            }
        });

        (async function initialize() {
            setBrainstormingFormEnabled(false);
            updateSubmitButtonState();
            showAccessMessage("");
            setStatus("Loading meeting…", "pending");
            await loadModuleCatalog();
            try {
                await loadMeetingDetails();
            } catch (error) {
                showAccessMessage(error.message || "Unable to load meeting.");
                setStatus("Access denied", "error");
                return;
            }
            renderAgenda(state.agenda);
            if (state.agenda.length > 0) {
                selectAgendaItem(state.agenda[0].activity_id, { source: "state" });
            }

            updateFacilitatorControls();
            if (ui.openParticipantAdminButton) {
                ui.openParticipantAdminButton.addEventListener("click", () => {
                    openParticipantAdminModal();
                });
            }
            if (ui.participantModalTabs?.length) {
                ui.participantModalTabs.forEach((tab) => {
                    tab.addEventListener("click", () => {
                        setParticipantModalMode(tab.dataset.participantModalTab);
                    });
                });
            }
            setStatus("Connecting…", "pending");
            connectRealtime();
            startMeetingRefresh();

            if (ui.facilitatorControls.participantForm && ui.facilitatorControls.participantInput) {
                ui.facilitatorControls.participantForm.addEventListener("submit", async (event) => {
                    event.preventDefault();
                    const login = ui.facilitatorControls.participantInput.value.trim();
                    if (!login) {
                        return;
                    }
                    if (ui.facilitatorControls.participantFeedback) {
                        ui.facilitatorControls.participantFeedback.textContent = "";
                    }
                    try {
                        await addAssignedParticipantByLogin(login);
                        ui.facilitatorControls.participantInput.value = "";
                    } catch (error) {
                        if (ui.facilitatorControls.participantFeedback) {
                            ui.facilitatorControls.participantFeedback.textContent = String(
                                error.message || error,
                            );
                        }
                    }
                });
            }
            if (ui.facilitatorControls.meetingDirectorySearch) {
                ui.facilitatorControls.meetingDirectorySearch.addEventListener("input", (event) => {
                    handleParticipantDirectorySearchInput(event.target.value || "");
                });
            }
            if (ui.facilitatorControls.meetingDirectoryClearButton) {
                ui.facilitatorControls.meetingDirectoryClearButton.addEventListener("click", () => {
                    clearParticipantDirectorySelection();
                });
            }
            if (ui.facilitatorControls.meetingAvailableSelectAll) {
                ui.facilitatorControls.meetingAvailableSelectAll.addEventListener("click", () => {
                    selectAllMeetingAvailable();
                });
            }
            if (ui.facilitatorControls.meetingSelectedSelectAll) {
                ui.facilitatorControls.meetingSelectedSelectAll.addEventListener("click", () => {
                    selectAllMeetingSelected();
                });
            }
            if (ui.facilitatorControls.meetingMoveToSelected) {
                ui.facilitatorControls.meetingMoveToSelected.addEventListener("click", () => {
                    addMeetingParticipantsFromSelection();
                });
            }
            if (ui.facilitatorControls.meetingMoveToAvailable) {
                ui.facilitatorControls.meetingMoveToAvailable.addEventListener("click", () => {
                    removeMeetingParticipantsFromSelection();
                });
            }
            if (ui.facilitatorControls.meetingDirectoryPrev) {
                ui.facilitatorControls.meetingDirectoryPrev.addEventListener("click", () => {
                    changeParticipantDirectoryPage(-1);
                });
            }
            if (ui.facilitatorControls.meetingDirectoryNext) {
                ui.facilitatorControls.meetingDirectoryNext.addEventListener("click", () => {
                    changeParticipantDirectoryPage(1);
                });
            }
            if (ui.facilitatorControls.activityIncludeAll) {
                ui.facilitatorControls.activityIncludeAll.addEventListener("click", async () => {
                    const activityId = activityParticipantState.currentActivityId;
                    if (!activityId) {
                        return;
                    }
                    const assignment = state.activityAssignments.get(activityId);
                    if (!assignment) {
                        await loadActivityParticipantAssignment(activityId, { force: true });
                        return;
                    }
                    activityParticipantState.mode = "all";
                    activityParticipantState.selection = new Set(
                        (assignment.available_participants || []).map((row) => row.user_id),
                    );
                    activityParticipantState.dirty = false;
                    await applyActivityParticipantSelection("all");
                });
            }
            if (ui.facilitatorControls.activityAvailableSelectAll) {
                ui.facilitatorControls.activityAvailableSelectAll.addEventListener("click", () => {
                    selectAllActivityAvailable();
                });
            }
            if (ui.facilitatorControls.activitySelectedSelectAll) {
                ui.facilitatorControls.activitySelectedSelectAll.addEventListener("click", () => {
                    selectAllActivitySelected();
                });
            }
            if (ui.facilitatorControls.activityMoveToSelected) {
                ui.facilitatorControls.activityMoveToSelected.addEventListener("click", () => {
                    addActivityParticipantsFromAvailable();
                });
            }
            if (ui.facilitatorControls.activityMoveToAvailable) {
                ui.facilitatorControls.activityMoveToAvailable.addEventListener("click", () => {
                    removeActivityParticipantsFromSelected();
                });
            }
            if (ui.facilitatorControls.activityReuse) {
                ui.facilitatorControls.activityReuse.addEventListener("click", async () => {
                    if (!activityParticipantState.lastCustomSelection) {
                        return;
                    }
                    activityParticipantState.selection = new Set(activityParticipantState.lastCustomSelection);
                    activityParticipantState.mode = "custom";
                    activityParticipantState.dirty = true;
                    // Re-render to show updated checkboxes
                    renderActivityParticipantSection(activityParticipantState.currentActivityId);
                    // Optional: Auto-apply? The prompt says "apply and reuse".
                    // Let's just set the state so user can review and click Apply.
                    setActivityParticipantFeedback("Previous selection loaded. Click Apply to save.", "info");
                });
            }
            if (ui.facilitatorControls.activityApply) {
                ui.facilitatorControls.activityApply.addEventListener("click", async () => {
                    await applyActivityParticipantSelection();
                });
            }
            // Add Activity Modal Logic
            if (ui.facilitatorControls.addActivityButton) {
                ui.facilitatorControls.addActivityButton.addEventListener("click", () => {
                    const settingsUrl = `/meeting/${encodeURIComponent(context.meetingId)}/settings`;
                    window.location.href = settingsUrl;
                });
            }

            function showCollisionModal(conflictingUsers, activeActivityId) {
                if (!ui.collisionModal) return;
                ui.collisionModal.hidden = false;

                const list = ui.conflictingParticipantsList;
                if (list) {
                    list.innerHTML = "";
                    if (conflictingUsers && conflictingUsers.length > 0) {
                        conflictingUsers.forEach(user => {
                            const li = document.createElement("li");
                            li.textContent = user.display_name || user.login || user.user_id || "Unknown User";
                            list.appendChild(li);
                        });
                    } else {
                        const li = document.createElement("li");
                        li.textContent = "No specific conflicting users identified.";
                        list.appendChild(li);
                    }
                }

                // Add event listeners for closing the modal
                if (ui.closeCollisionModal) {
                    ui.closeCollisionModal.onclick = hideCollisionModal;
                }
                if (ui.cancelCollision) {
                    ui.cancelCollision.onclick = hideCollisionModal;
                }
            }

            function hideCollisionModal() {
                if (ui.collisionModal) {
                    ui.collisionModal.hidden = true;
                }
                if (ui.conflictingParticipantsList) {
                    ui.conflictingParticipantsList.innerHTML = "";
                }
            }


            if (transfer.close) {
                transfer.close.addEventListener("click", closeTransferModal);
            }
            if (transfer.addIdea) {
                transfer.addIdea.addEventListener("click", addTransferIdea);
            }
            if (transfer.saveDraft) {
                transfer.saveDraft.addEventListener("click", () => saveTransferDraft(false));
            }
            if (transfer.commit) {
                transfer.commit.addEventListener("click", commitTransfer);
            }
            if (transfer.includeComments) {
                transfer.includeComments.addEventListener("change", () => {
                    transferState.includeComments = transfer.includeComments.checked;
                    transferState.dirty = true;
                    setTransferStatus("Unsaved changes.", "muted");
                    renderTransferIdeas();
                    setTransferButtonsState();
                    scheduleTransferAutosave();
                });
            }
            if (transfer.targetToolType) {
                buildTransferTargetOptions();
            }
            if (transfer.transformProfile) {
                transfer.transformProfile.addEventListener("change", async () => {
                    transferState.transformProfile = getActiveTransferProfile();
                    transferState.dirty = false;
                    setTransferStatus("Loading transformed transfer bundle...", "info");
                    await loadTransferBundles();
                });
            }
            // Transfer panel is inline; no modal click handler.
        })(); // end initialize
    }); // end DOMContentLoaded
})(); // end IIFE wrapper
