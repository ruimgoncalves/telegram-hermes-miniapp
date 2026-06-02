// Hermes Secrets — Telegram Mini App
// Static page. Talks to the Hermes secrets API when available, falls back
// to localStorage when running in a plain browser without the Mini App SDK.

(function () {
  'use strict';

  // ---- Config ----
  const API_BASE = 'https://hermes.localdomain/secrets-api';
  const STORAGE_KEY = 'hermes-miniapp-secrets';

  // ---- Telegram Mini App bootstrap (safe in plain browser) ----
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    try { tg.ready(); tg.expand(); } catch (e) { /* no-op outside Telegram */ }
  }
  const inTelegram = !!(tg && tg.initData);

  // Best-effort init data. In a real Telegram client, window.Telegram.WebApp.initData
  // is a non-empty string. Outside Telegram (plain browser, dev tools) we fall back
  // to localStorage so the page is still usable.
  function telegramInitData() {
    if (tg && typeof tg.initData === 'string' && tg.initData.length > 0) {
      return tg.initData;
    }
    return null;
  }

  // ---- Storage (offline / non-Telegram fallback) ----
  function loadSecrets() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) { return []; }
  }
  function saveSecrets(secrets) {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(secrets)); return true; }
    catch (e) { return false; }
  }

  // ---- API client ----
  async function api(method, path, body) {
    const initData = telegramInitData();
    const headers = { 'Content-Type': 'application/json' };
    if (initData) headers['X-Telegram-Init-Data'] = initData;
    const res = await fetch(API_BASE + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const j = await res.json();
        detail = j.detail || detail;
      } catch (_) { /* ignore */ }
      const err = new Error(detail);
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  }

  // ---- DOM refs ----
  const menuBtn = document.getElementById('menuBtn');
  const closeMenuBtn = document.getElementById('closeMenuBtn');
  const sideMenu = document.getElementById('sideMenu');
  const menuBackdrop = document.getElementById('menuBackdrop');
  const menuItems = document.querySelectorAll('.menu-item');
  const apiBaseLabel = document.getElementById('apiBaseLabel');

  const views = {
    add: document.getElementById('view-add'),
    view: document.getElementById('view-view'),
    about: document.getElementById('view-about'),
  };

  const form = document.getElementById('secretForm');
  const nameInput = document.getElementById('nameInput');
  const valueInput = document.getElementById('valueInput');
  const toggleValueBtn = document.getElementById('toggleValueBtn');
  const sizeHint = document.getElementById('sizeHint');
  const errorMsg = document.getElementById('errorMsg');
  const submitBtn = document.getElementById('submitBtn');
  const addSub = document.getElementById('addSub');

  const refreshBtn = document.getElementById('refreshBtn');
  const secretList = document.getElementById('secretList');
  const listMsg = document.getElementById('listMsg');
  const listMeta = document.getElementById('listMeta');

  const connBanner = document.getElementById('connBanner');

  // ---- Side menu ----
  function openMenu() {
    sideMenu.classList.add('open');
    sideMenu.setAttribute('aria-hidden', 'false');
  }
  function closeMenu() {
    sideMenu.classList.remove('open');
    sideMenu.setAttribute('aria-hidden', 'true');
  }
  menuBtn.addEventListener('click', openMenu);
  closeMenuBtn.addEventListener('click', closeMenu);
  menuBackdrop.addEventListener('click', closeMenu);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sideMenu.classList.contains('open')) closeMenu();
  });

  // ---- View switching ----
  function showView(name) {
    Object.entries(views).forEach(([key, el]) => {
      if (!el) return;
      el.classList.toggle('active', key === name);
    });
    menuItems.forEach((item) => {
      item.classList.toggle('active', item.dataset.view === name);
    });
    closeMenu();
    if (name === 'add') showError('');
    if (name === 'view') loadSecretList();
  }
  menuItems.forEach((item) => {
    item.addEventListener('click', () => {
      const target = item.dataset.view;
      if (target && views[target]) showView(target);
    });
  });

  // ---- Size hint ----
  function formatBytes(n) {
    if (n === 0) return '0 bytes';
    if (n === 1) return '1 byte';
    return n + ' bytes';
  }
  function updateSizeHint() {
    const bytes = new TextEncoder().encode(valueInput.value || '').length;
    sizeHint.textContent = formatBytes(bytes);
  }
  valueInput.addEventListener('input', updateSizeHint);
  updateSizeHint();

  // ---- Toggle value visibility ----
  toggleValueBtn.addEventListener('click', () => {
    const showing = valueInput.type === 'text';
    valueInput.type = showing ? 'password' : 'text';
    toggleValueBtn.textContent = showing ? '👁' : '🙈';
    toggleValueBtn.setAttribute('aria-label', showing ? 'Show value' : 'Hide value');
  });

  // ---- Inline message under the form (errors red, success green) ----
  function showError(msg) {
    errorMsg.textContent = msg || '';
    if (msg && msg.trim().startsWith('✓')) {
      errorMsg.classList.add('success');
    } else {
      errorMsg.classList.remove('success');
    }
  }

  // ---- Connection banner (top of page) ----
  function setConnBanner(state, text) {
    connBanner.hidden = false;
    connBanner.classList.toggle('ok', state === 'ok');
    connBanner.textContent = text;
  }
  function clearConnBanner() { connBanner.hidden = true; connBanner.textContent = ''; }

  // ---- API health check (runs once at startup) ----
  async function checkApi() {
    apiBaseLabel.textContent = API_BASE;
    if (!inTelegram) {
      setConnBanner(
        'warn',
        'Not running inside Telegram — saving will use local browser storage. Open the Mini App from your bot for real writes.'
      );
      addSub.textContent = 'localStorage fallback (not in Telegram).';
      return;
    }
    try {
      const r = await api('GET', '/healthz');
      if (r && r.status === 'ok') {
        setConnBanner('ok', `Connected to vault (${r.secret_count} secret${r.secret_count === 1 ? '' : 's'} on file).`);
      } else {
        setConnBanner('warn', 'Vault responded with an unexpected status.');
      }
    } catch (e) {
      setConnBanner('warn', `Vault unreachable: ${e.message || e}. Saving will fall back to local storage.`);
    }
  }

  // ---- Form submit ----
  function setSubmitting(isSubmitting) {
    submitBtn.disabled = isSubmitting;
    submitBtn.textContent = isSubmitting ? 'Saving…' : 'Save Secret';
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    showError('');

    const name = nameInput.value.trim();
    const value = valueInput.value;

    if (!name) { showError('Secret name is required.'); nameInput.focus(); return; }
    if (!/^[A-Za-z0-9_.-]+$/.test(name)) {
      showError('Name may only contain letters, digits, "_", "." and "-".');
      nameInput.focus();
      return;
    }
    if (!value) { showError('Secret value is required.'); valueInput.focus(); return; }

    setSubmitting(true);
    try {
      if (inTelegram) {
        await api('POST', '/v1/secrets', { name, value });
      } else {
        // Local fallback
        const secrets = loadSecrets();
        if (secrets.some(s => s.name.toLowerCase() === name.toLowerCase())) {
          throw new Error(`A secret named "${name}" already exists.`);
        }
        secrets.push({ name, value });
        if (!saveSecrets(secrets)) throw new Error('localStorage write failed.');
      }
      nameInput.value = '';
      valueInput.value = '';
      updateSizeHint();
      showError(`✓ Saved "${name}".`);
      setTimeout(() => { if (errorMsg.textContent.startsWith('✓')) showError(''); }, 2500);
      nameInput.focus();
      // Refresh the banner count after a successful write
      checkApi();
    } catch (err) {
      showError(err.message || String(err));
    } finally {
      setSubmitting(false);
    }
  });

  // ---- Secret list (View Secrets) ----
  refreshBtn.addEventListener('click', loadSecretList);

  function renderList(secrets) {
    secretList.innerHTML = '';
    listMsg.textContent = '';
    if (!secrets || secrets.length === 0) {
      listMsg.textContent = inTelegram ? 'No secrets yet — add one from the menu.' : 'No secrets in local storage.';
      listMeta.textContent = '';
      return;
    }
    listMeta.textContent = `${secrets.length} secret${secrets.length === 1 ? '' : 's'}`;
    for (const s of secrets) {
      const li = document.createElement('li');
      li.className = 'secret-item';
      li.dataset.name = s.name;

      const nameSpan = document.createElement('span');
      nameSpan.className = 'name';
      nameSpan.textContent = s.name;

      const actions = document.createElement('div');
      actions.className = 'actions';

      const revealBtn = document.createElement('button');
      revealBtn.className = 'icon-btn small';
      revealBtn.textContent = '👁';
      revealBtn.title = 'Reveal value';
      revealBtn.setAttribute('aria-label', `Reveal value of ${s.name}`);
      revealBtn.addEventListener('click', () => revealSecret(s.name, li));

      const delBtn = document.createElement('button');
      delBtn.className = 'icon-btn small';
      delBtn.textContent = '🗑';
      delBtn.title = 'Delete';
      delBtn.setAttribute('aria-label', `Delete ${s.name}`);
      delBtn.addEventListener('click', () => deleteSecret(s.name));

      actions.appendChild(revealBtn);
      actions.appendChild(delBtn);

      li.appendChild(nameSpan);
      li.appendChild(actions);
      secretList.appendChild(li);
    }
  }

  async function loadSecretList() {
    listMsg.textContent = 'Loading…';
    listMeta.textContent = '';
    try {
      let secrets;
      if (inTelegram) {
        const r = await api('GET', '/v1/secrets');
        secrets = r.secrets || [];
      } else {
        secrets = loadSecrets().map(s => ({ name: s.name }));
      }
      renderList(secrets);
    } catch (e) {
      listMsg.textContent = `Failed to load: ${e.message || e}`;
    }
  }

  async function deleteSecret(name) {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    try {
      if (inTelegram) {
        await api('DELETE', '/v1/secrets/' + encodeURIComponent(name));
      } else {
        const secrets = loadSecrets().filter(s => s.name !== name);
        if (!saveSecrets(secrets)) throw new Error('localStorage write failed.');
      }
      await loadSecretList();
      checkApi();
    } catch (e) {
      listMsg.textContent = `Delete failed: ${e.message || e}`;
    }
  }

  async function revealSecret(name, li) {
    try {
      let value;
      if (inTelegram) {
        const r = await api('GET', '/v1/secrets/' + encodeURIComponent(name));
        value = r.value;
      } else {
        const s = loadSecrets().find(x => x.name === name);
        value = s ? s.value : null;
      }
      if (value == null) {
        listMsg.textContent = `No value found for "${name}".`;
        return;
      }
      // Inject (or replace) a value span between name and actions.
      let valSpan = li.querySelector('.value');
      if (!valSpan) {
        valSpan = document.createElement('span');
        valSpan.className = 'value';
        li.insertBefore(valSpan, li.querySelector('.actions'));
      }
      valSpan.textContent = value;
    } catch (e) {
      listMsg.textContent = `Reveal failed: ${e.message || e}`;
    }
  }

  // ---- Boot ----
  checkApi();
})();
