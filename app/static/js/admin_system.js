(() => {
    const POLL_INTERVAL_MS = 1500;
    const POLL_TIMEOUT_MS = 30000;

    function buildOverlay(supervised) {
        const overlay = document.createElement('div');
        overlay.id = 'systemRestartOverlay';
        overlay.style.cssText = [
            'position:fixed', 'inset:0', 'z-index:9999',
            'background:rgba(0,0,0,0.82)', 'color:#fff',
            'display:flex', 'flex-direction:column',
            'align-items:center', 'justify-content:center',
            'gap:16px', 'text-align:center', 'padding:32px',
        ].join(';');

        const heading = document.createElement('h2');
        heading.style.cssText = 'margin:0;font-size:1.5rem;';

        const sub = document.createElement('p');
        sub.style.cssText = 'margin:0;opacity:0.8;max-width:380px;';

        if (supervised) {
            heading.textContent = 'Restarting…';
            sub.textContent = 'The server is coming back up. This usually takes less than 10 seconds.';
        } else {
            heading.textContent = 'Server stopped.';
            sub.textContent = 'Restart it from the terminal to reconnect, then refresh this page.';
        }

        overlay.appendChild(heading);
        overlay.appendChild(sub);
        return { overlay, heading, sub };
    }

    async function pollUntilAlive(heading, sub) {
        const deadline = Date.now() + POLL_TIMEOUT_MS;
        while (Date.now() < deadline) {
            await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
            try {
                const resp = await fetch('/login', { method: 'GET', credentials: 'include' });
                if (resp.ok || resp.status === 302) {
                    heading.textContent = 'Back online!';
                    sub.textContent = 'Redirecting to login…';
                    await new Promise(resolve => setTimeout(resolve, 800));
                    window.location.href = '/login';
                    return;
                }
            } catch (_) {
                // server not yet reachable — keep polling
            }
        }
        heading.textContent = 'Taking longer than expected.';
        sub.textContent = 'Check the server status, then refresh this page manually.';
    }

    function confirmAndExecute(btn) {
        const supervised = btn.dataset.supervised === 'true';
        const action = supervised ? 'restart' : 'shut down';
        const warning = supervised
            ? 'Active meetings will lose their connections for ~10 seconds.'
            : 'The server will stop and must be restarted manually from the terminal.';

        const confirmed = window.confirm(
            `Are you sure you want to ${action} the server?\n\n${warning}`
        );
        if (!confirmed) return;

        btn.disabled = true;

        fetch('/api/settings/restart', { method: 'POST', credentials: 'include' })
            .then(resp => {
                if (!resp.ok) {
                    return resp.json().then(body => {
                        throw new Error(body?.detail || `Server returned ${resp.status}`);
                    });
                }
                const { overlay, heading, sub } = buildOverlay(supervised);
                document.body.appendChild(overlay);
                if (supervised) {
                    pollUntilAlive(heading, sub);
                }
            })
            .catch(err => {
                btn.disabled = false;
                alert(`Could not ${action} the server: ${err.message}`);
            });
    }

    document.addEventListener('DOMContentLoaded', () => {
        const btn = document.getElementById('systemRestartBtn');
        if (!btn) return;
        btn.addEventListener('click', () => confirmAndExecute(btn));
    });
})();
