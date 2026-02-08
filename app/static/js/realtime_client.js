(() => {
    const DEFAULT_RETRY_LIMIT = 3;
    const DEFAULT_RETRY_DELAY = 2000;

    /**
     * Lightweight helper that wraps the browser WebSocket API and exposes a
     * callback-driven interface tailored for meeting connections.
     */
    class MeetingSocket {
        constructor({
            meetingId,
            clientId,
            onOpen,
            onClose,
            onError,
            onMessage,
            retryLimit = DEFAULT_RETRY_LIMIT,
            retryDelay = DEFAULT_RETRY_DELAY
        }) {
            this.meetingId = meetingId;
            this.clientId = clientId;
            this.retryLimit = retryLimit;
            this.retryDelay = retryDelay;
            this.retryCount = 0;
            this.handlers = {
                open: onOpen,
                close: onClose,
                error: onError,
                message: onMessage
            };
            this.socket = null;
            this.connectionId = null;
            this.closedByClient = false;
            this.connect();
        }

        connect() {
            if (!("WebSocket" in window)) {
                console.warn("WebSocket support is not available in this browser.");
                return;
            }

            const params = new URLSearchParams();
            if (this.clientId) {
                params.set("clientId", this.clientId);
            }

            const url = `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}/ws/meetings/${encodeURIComponent(this.meetingId)}${params.toString() ? `?${params.toString()}` : ""}`;
            this.socket = new WebSocket(url);

            this.socket.onopen = (event) => {
                this.retryCount = 0;
                this.invokeHandler("open", event);
            };

            this.socket.onclose = (event) => {
                this.invokeHandler("close", event);
                this.connectionId = null;
                if (this.closedByClient) {
                    return;
                }
                if (this.retryCount < this.retryLimit) {
                    this.retryCount += 1;
                    setTimeout(() => this.connect(), this.retryDelay * this.retryCount);
                }
            };

            this.socket.onerror = (event) => {
                this.invokeHandler("error", event);
            };

            this.socket.onmessage = (event) => {
                this.handleIncoming(event);
            };
        }

        invokeHandler(type, event) {
            const handler = this.handlers[type];
            if (typeof handler === "function") {
                try {
                    handler(event, this);
                } catch (error) {
                    console.error(`Realtime handler '${type}' threw an error`, error);
                }
            }
        }

        handleIncoming(event) {
            let payload;
            try {
                payload = JSON.parse(event.data);
            } catch (error) {
                console.warn("Ignoring malformed WebSocket message:", event.data);
                return;
            }

            if (payload?.type === "connection_ack") {
                this.connectionId = payload?.payload?.connectionId ?? null;
            }

            const handler = this.handlers.message;
            if (typeof handler === "function") {
                try {
                    handler(payload, this);
                } catch (error) {
                    console.error("Realtime onMessage handler threw an error", error);
                }
            }
        }

        send(type, messagePayload = {}, extra = {}) {
            if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
                console.warn("Attempted to send on a closed WebSocket connection.");
                return false;
            }

            const body = {
                type,
                payload: messagePayload,
                ...extra
            };

            this.socket.send(JSON.stringify(body));
            return true;
        }

        close(code = 1000, reason = "client-close") {
            this.closedByClient = true;
            if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
                this.socket.close(code, reason);
            }
        }
    }

    window.DecideroRealtime = {
        createMeetingSocket(options) {
            if (!options || !options.meetingId) {
                throw new Error("Missing meetingId for meeting socket creation.");
            }
            return new MeetingSocket(options);
        }
    };
})();
