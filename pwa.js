/* The Porch Project — app helper
 * 1. Turns on the service worker (fast loads + offline fallback).
 * 2. Shows returning mobile visitors a gentle "Add Porch to your phone" banner.
 *    - iPhone (Safari): shows the Share → Add to Home Screen steps.
 *    - Android/Chrome: one-tap install button.
 *    - Never shows on desktop, inside the installed app, on a first visit,
 *      or for 21 days after someone closes it.
 * 3. Sends GA4 events so you can see installs:
 *    pwa_launch (launch_mode = browser | installed_app), pwa_banner_shown,
 *    pwa_banner_dismissed, pwa_install_clicked, pwa_installed.
 */
(function () {
  if (window.__ppPwa) return;
  window.__ppPwa = true;

  function track(name, params) {
    try { if (typeof gtag === 'function') gtag('event', name, params || {}); } catch (e) {}
  }
  function get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }

  var standalone = (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
                   window.navigator.standalone === true;

  // 1. Service worker
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {});
    });
  }

  // 3. Launch tracking (once per page session)
  window.addEventListener('load', function () {
    track('pwa_launch', { launch_mode: standalone ? 'installed_app' : 'browser' });
  });
  window.addEventListener('appinstalled', function () {
    track('pwa_installed');
    set('pp_install_dismissed', String(Date.now()));
    hide();
  });

  // 2. Install banner
  if (standalone) return;
  var ua = navigator.userAgent || '';
  var isIOS = /iPhone|iPad|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var isIOSSafari = isIOS && /Safari/.test(ua) && !/CriOS|FxiOS|EdgiOS|GSA|FBAN|FBAV|Instagram/.test(ua);
  var isMobile = isIOS || /Android/.test(ua);
  if (!isMobile) return;

  var DISMISS_DAYS = 21;
  var last = parseInt(get('pp_install_dismissed') || '0', 10);
  if (last && Date.now() - last < DISMISS_DAYS * 86400000) return;

  // Count visits; only nudge returning neighbors (2nd visit onward).
  var visits = parseInt(get('pp_visits') || '0', 10);
  if (!sessionStorageFlag()) set('pp_visits', String(visits + 1));
  function sessionStorageFlag() {
    try {
      if (sessionStorage.getItem('pp_visit_counted')) return true;
      sessionStorage.setItem('pp_visit_counted', '1');
    } catch (e) {}
    return false;
  }
  if (visits < 1) return;

  var deferredPrompt = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;
  });

  var el;
  function hide() { if (el) { el.classList.remove('pp-show'); setTimeout(function () { el && el.remove(); }, 300); } }

  function build() {
    // Don't stack on top of the newsletter pop-up.
    var nl = document.getElementById('ppNewsletter');
    if (nl && nl.classList.contains('open')) { setTimeout(build, 4000); return; }

    var canPrompt = !!deferredPrompt;
    if (!isIOSSafari && !canPrompt) {
      // In-app browsers (Facebook, Instagram) and iOS Chrome can't add to home screen easily.
      if (!isIOS) return;
    }

    var css = document.createElement('style');
    css.textContent =
      '.pp-install{position:fixed;left:12px;right:12px;bottom:calc(12px + env(safe-area-inset-bottom));z-index:9998;' +
      'background:#2C3E2D;color:#FAF5EF;border-radius:16px;padding:14px 14px 14px 16px;display:flex;gap:12px;align-items:center;' +
      'box-shadow:0 10px 30px rgba(44,62,45,.28);font-family:"DM Sans",-apple-system,sans-serif;font-size:.92rem;line-height:1.4;' +
      'transform:translateY(140%);transition:transform .3s ease;max-width:520px;margin:0 auto}' +
      '.pp-install.pp-show{transform:none}' +
      '.pp-install img{width:44px;height:44px;border-radius:10px;flex:none;box-shadow:0 0 0 1px rgba(250,245,239,.35)}' +
      '.pp-install b{display:block;font-size:.98rem;margin-bottom:2px}' +
      '.pp-install .pp-msg{flex:1}' +
      '.pp-install .pp-go{background:#E9A752;color:#2C3E2D;border:0;border-radius:999px;padding:8px 14px;font-weight:700;font-size:.88rem;flex:none}' +
      '.pp-install .pp-x{background:none;border:0;color:#ACCAB2;font-size:1.4rem;line-height:1;padding:4px 6px;flex:none;cursor:pointer}' +
      '.pp-share{display:inline-block;width:14px;height:16px;vertical-align:-2px;margin:0 2px}';
    document.head.appendChild(css);

    el = document.createElement('div');
    el.className = 'pp-install';
    el.setAttribute('role', 'dialog');
    el.setAttribute('aria-label', 'Add The Porch Project to your home screen');

    var shareIcon = '<svg class="pp-share" viewBox="0 0 14 16" fill="none" stroke="#FAF5EF" stroke-width="1.6" aria-hidden="true"><path d="M7 1v9M3.5 4.5 7 1l3.5 3.5M2 7.5v7h10v-7"/></svg>';
    var msg;
    if (canPrompt) {
      msg = '<b>Keep Porch on your phone</b>One tap to add it — no app store needed.';
    } else if (isIOSSafari) {
      msg = '<b>Keep Porch on your phone</b>Tap ' + shareIcon + ' Share, then <b style="display:inline">Add to Home Screen</b>.';
    } else {
      msg = '<b>Keep Porch on your phone</b>Open porchproject.co in Safari, tap Share, then Add to Home Screen.';
    }

    el.innerHTML = '<img src="/icons/icon-96.png" alt=""><div class="pp-msg">' + msg + '</div>' +
      (canPrompt ? '<button class="pp-go" type="button">Add</button>' : '') +
      '<button class="pp-x" type="button" aria-label="Close">&times;</button>';
    document.body.appendChild(el);
    requestAnimationFrame(function () { requestAnimationFrame(function () { el.classList.add('pp-show'); }); });
    track('pwa_banner_shown', { platform: canPrompt ? 'android' : 'ios' });

    el.querySelector('.pp-x').addEventListener('click', function () {
      set('pp_install_dismissed', String(Date.now()));
      track('pwa_banner_dismissed');
      hide();
    });
    var go = el.querySelector('.pp-go');
    if (go) go.addEventListener('click', function () {
      track('pwa_install_clicked');
      deferredPrompt.prompt();
      deferredPrompt.userChoice.finally(function () { deferredPrompt = null; hide(); });
    });
  }

  window.addEventListener('load', function () { setTimeout(build, 6000); });
})();
