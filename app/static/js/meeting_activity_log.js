(() => {
    document.addEventListener("DOMContentLoaded", () => {
        const root = document.querySelector("[data-meeting-activity-log]");
        if (!root) {
            return;
        }

        const meetingId = root.dataset.meetingId;
        if (!meetingId) {
            console.warn("Activity log page missing meetingId context.");
            return;
        }

        const realtimeAvailable = Boolean(window.DecideroRealtime);
        const eventsLog = document.getElementById("meetingActivityLog");
        const statusBadge = document.getElementById("activityLogConnectionStatus");
        const maxItems = Number.parseInt(root.dataset.maxItems || "100", 10) || 100;
        const userId = root.dataset.userId || null;

        if (!eventsLog) {
            return;
        }

        const state = {
            latestState: null,
        };

        let meetingSocket = null;
        let heartbeatTimer = null;

        function setStatus(label, variant) {
            if (!statusBadge) {
                return;
            }
            statusBadge.textContent = label;
            if (variant) {
                statusBadge.dataset.statusVariant = variant;
            }
        }

        function updateLogMaxHeight() {
            const sampleItem = eventsLog.querySelector("li");
            if (!sampleItem) {
                return;
            }
            const itemHeight = sampleItem.getBoundingClientRect().height;
            if (!itemHeight) {
                return;
            }
            const styles = window.getComputedStyle(eventsLog);
            const gapValue = styles.rowGap || styles.gap || "0";
            const gap = Number.parseFloat(gapValue) || 0;
            const totalHeight = itemHeight * maxItems + gap * Math.max(0, maxItems - 1);
            eventsLog.style.maxHeight = `${Math.ceil(totalHeight)}px`;
        }

        function logEvent(message) {
            const normalized = (message || "").trim();
            if (!normalized || normalized === "Heartbeat acknowledged.") {
                return;
            }
            const row = document.createElement("li");
            row.textContent = `[${new Date().toLocaleTimeString()}] ${normalized}`;

            if (
                eventsLog.children.length === 1 &&
                eventsLog.children[0].textContent === "Waiting for events..."
            ) {
                eventsLog.innerHTML = "";
            }

            eventsLog.prepend(row);
            while (eventsLog.children.length > maxItems) {
                eventsLog.removeChild(eventsLog.lastElementChild);
            }
        }

        function handleStateSnapshot(snapshot, emitLog = false) {
            if (!snapshot) {
                state.latestState = null;
                if (emitLog) {
                    logEvent("Meeting state cleared.");
                }
                return;
            }

            state.latestState = {
                status: snapshot.status ?? state.latestState?.status ?? null,
                currentActivity: snapshot.currentActivity ?? snapshot.agendaItemId ?? null,
                currentTool: snapshot.currentTool ?? null,
            };

            if (emitLog) {
                const activityLabel = state.latestState.currentActivity || "unknown activity";
                const toolLabel = state.latestState.currentTool ? ` tool ${state.latestState.currentTool}` : "";
                logEvent(`Meeting state updated: ${activityLabel}${toolLabel}`);
            }
        }

        function handleRealtimeMessage(message) {
            const { type, payload } = message || {};
            switch (type) {
                case "connection_ack":
                    setStatus("Connected", "success");
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent("Connected to meeting.");
                    break;
                case "participant_joined":
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent(`Participant joined: ${payload?.userId || payload?.connectionId}`);
                    break;
                case "participant_left":
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent(`Participant left: ${payload?.userId || payload?.connectionId}`);
                    break;
                case "participant_identified":
                    handleStateSnapshot(payload?.state, Boolean(payload?.state));
                    logEvent(`Participant identified: ${payload?.userId || payload?.connectionId}`);
                    break;
                case "pong":
                    logEvent("Heartbeat acknowledged.");
                    break;
                case "meeting_state":
                    handleStateSnapshot(payload, true);
                    break;
                case "agenda_update":
                    logEvent("Agenda updated in real-time.");
                    break;
                case "new_idea":
                    logEvent("New brainstorming idea received.");
                    break;
                default:
                    logEvent(`Event received: ${type || "unknown"}`);
                    break;
            }
        }

        function connectRealtime() {
            if (!realtimeAvailable) {
                setStatus("Realtime unavailable", "warning");
                return;
            }

            meetingSocket = window.DecideroRealtime.createMeetingSocket({
                meetingId,
                clientId: userId || undefined,
                onOpen: () => {
                    setStatus("Connected", "success");
                    if (userId) {
                        meetingSocket.send("identify", { userId });
                    }
                    meetingSocket.send("state_request");
                },
                onClose: () => {
                    setStatus("Disconnected", "warning");
                    handleStateSnapshot(null, true);
                },
                onError: () => {
                    setStatus("Error", "error");
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

        updateLogMaxHeight();
        setStatus("Connecting...", "pending");
        connectRealtime();
    });
})();
