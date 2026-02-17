(() => {
  const DEFAULT_RETRYABLE_STATUSES = new Set([429, 502, 503, 504]);

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function generateRequestId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  function computeBackoffMs(attempt, baseDelayMs, maxDelayMs, jitterRatio) {
    const expDelay = Math.min(maxDelayMs, baseDelayMs * Math.pow(2, attempt));
    const jitter = expDelay * jitterRatio * Math.random();
    return Math.round(expDelay + jitter);
  }

  function isLikelyTransientNetworkError(error) {
    if (!error) return false;
    const name = String(error.name || "");
    if (name === "AbortError" || name === "TypeError") {
      return true;
    }
    const message = String(error.message || "").toLowerCase();
    return (
      message.includes("networkerror") ||
      message.includes("failed to fetch") ||
      message.includes("network request failed")
    );
  }

  async function runWithRetry(task, options = {}) {
    const maxRetries = Number.isFinite(options.maxRetries) ? Math.max(0, options.maxRetries) : 3;
    const baseDelayMs = Number.isFinite(options.baseDelayMs) ? Math.max(1, options.baseDelayMs) : 400;
    const maxDelayMs = Number.isFinite(options.maxDelayMs) ? Math.max(baseDelayMs, options.maxDelayMs) : 4000;
    const jitterRatio = Number.isFinite(options.jitterRatio) ? Math.max(0, options.jitterRatio) : 0.2;
    const requestId = options.requestId || generateRequestId();
    const shouldRetryResult =
      typeof options.shouldRetryResult === "function"
        ? options.shouldRetryResult
        : (result) => Boolean(result && DEFAULT_RETRYABLE_STATUSES.has(result.status));
    const shouldRetryError =
      typeof options.shouldRetryError === "function"
        ? options.shouldRetryError
        : isLikelyTransientNetworkError;

    let lastFailure = null;
    for (let attempt = 0; attempt <= maxRetries; attempt += 1) {
      try {
        const result = await task({ attempt, requestId });
        const retryable = shouldRetryResult(result, { attempt, requestId });
        if (!retryable || attempt >= maxRetries) {
          return result;
        }
        const delayMs = computeBackoffMs(attempt, baseDelayMs, maxDelayMs, jitterRatio);
        if (typeof options.onRetry === "function") {
          options.onRetry({
            attempt,
            requestId,
            delayMs,
            reason: "retryable_result",
            result,
          });
        }
        await sleep(delayMs);
      } catch (error) {
        lastFailure = error;
        const retryable = shouldRetryError(error, { attempt, requestId });
        if (!retryable || attempt >= maxRetries) {
          throw error;
        }
        const delayMs = computeBackoffMs(attempt, baseDelayMs, maxDelayMs, jitterRatio);
        if (typeof options.onRetry === "function") {
          options.onRetry({
            attempt,
            requestId,
            delayMs,
            reason: "retryable_error",
            error,
          });
        }
        await sleep(delayMs);
      }
    }
    throw lastFailure || new Error("Retry runner exhausted.");
  }

  function createSerialQueue(name = "default") {
    let tail = Promise.resolve();
    return {
      name,
      enqueue(task) {
        const run = tail.catch(() => undefined).then(() => task());
        tail = run.catch(() => undefined);
        return run;
      },
    };
  }

  window.DecideroReliableActions = {
    runWithRetry,
    createSerialQueue,
    generateRequestId,
    isLikelyTransientNetworkError,
  };
})();
