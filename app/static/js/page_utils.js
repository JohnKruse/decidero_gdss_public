(() => {
  const bannerEl = () => document.getElementById('pageError');

  function setVariantStyles(el, variant) {
    // Minimal inline styling to avoid requiring extra CSS
    const styles = {
      info: { bg: 'rgba(11, 61, 145, 0.10)', color: '#0B3D91' },
      success: { bg: 'rgba(76, 175, 80, 0.12)', color: '#2f7d32' },
      error: { bg: 'rgba(255, 0, 0, 0.12)', color: '#b00020' }
    };
    const s = styles[variant] || styles.info;
    el.style.background = s.bg;
    el.style.color = s.color;
  }

  window.showBanner = (message, variant = 'info', timeoutMs = 4000) => {
    const el = bannerEl();
    if (!el) return;
    el.textContent = message || '';
    setVariantStyles(el, variant);
    el.style.position = 'fixed';
    el.style.left = '50%';
    el.style.top = '50%';
    el.style.transform = 'translate(-50%, -50%)';
    el.style.padding = '0.22rem 1.2rem';
    el.style.borderRadius = '10px';
    el.style.background = '#ffffff';
    el.style.border = '2px solid #b00020';
    el.style.color = '#b00020';
    el.style.boxShadow = '0 10px 24px rgba(0, 0, 0, 0.18)';
    el.style.zIndex = '9999';
    el.style.maxWidth = '420px';
    el.style.width = 'auto';
    el.style.textAlign = 'center';
    el.style.fontSize = '1.5rem';
    el.hidden = false;
    if (timeoutMs > 0) {
      setTimeout(() => { el.hidden = true; }, timeoutMs);
    }
  };

  if (typeof window.fetch === 'function' && !window.__decideroFetchWrapped) {
    window.__decideroFetchWrapped = true;
    const originalFetch = window.fetch.bind(window);
    const redirectToLogin = (() => {
      let redirecting = false;
      return () => {
        if (redirecting) return;
        redirecting = true;
        const next = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
        if (typeof window.showBanner === 'function') {
          window.showBanner('Your session expired. Please sign in again.', 'error', 4000);
        }
        setTimeout(() => {
          window.location.href = `/login?message=login_required&next=${next}`;
        }, 4000);
      };
    })();

    window.fetch = async (input, init) => {
      const response = await originalFetch(input, init);
      try {
        if (response.status === 401) {
          const url =
            typeof input === 'string'
              ? input
              : input && input.url
                ? input.url
                : '';
          if (url.includes('/api/')) {
            redirectToLogin();
          }
        }
      } catch (error) {
        console.warn('Auth redirect check failed.', error);
      }
      return response;
    };
  }
})();
