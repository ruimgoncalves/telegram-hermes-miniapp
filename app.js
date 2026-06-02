// Hermes Secrets — Telegram Mini App
// Static page. Secrets stored in localStorage only.

(function () {
  'use strict';

  // ---- Telegram Mini App bootstrap (safe in plain browser) ----
  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    try { tg.ready(); tg.expand(); } catch (e) { /* no-op outside Telegram */ }
  }

  // ---- Storage ----
  const STORAGE_KEY = 'hermes-miniapp-secrets';

  function loadSecrets() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      console.warn('Failed to read secrets from localStorage:', e);
      return [];
    }
  }

  function saveSecrets(secrets) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(secrets));
      return true;
    } catch (e) {
      console.error('Failed to write secrets to localStorage:', e);
      return false;
    }
  }

  function secretExists(name) {
    const secrets = loadSecrets();
    const target = name.toLowerCase();
    return secrets.some(s => s.name && s.name.toLowerCase() === target);
  }

  // ---- DOM refs ----
  const menuBtn = document.getElementById('menuBtn');
  const closeMenuBtn = document.getElementById('closeMenuBtn');
  const sideMenu = document.getElementById('sideMenu');
  const menuBackdrop = document.getElementById('menuBackdrop');
  const menuItems = document.querySelectorAll('.menu-item');

  const views = {
    add: document.getElementById('view-add'),
    about: document.getElementById('view-about'),
  };

  const form = document.getElementById('secretForm');
  const nameInput = document.getElementById('nameInput');
  const valueInput = document.getElementById('valueInput');
  const toggleValueBtn = document.getElementById('toggleValueBtn');
  const sizeHint = document.getElementById('sizeHint');
  const errorMsg = document.getElementById('errorMsg');
  const submitBtn = document.getElementById('submitBtn');

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
    if (name === 'add') {
      // clear any stale error when returning to the form
      showError('');
    }
  }
  menuItems.forEach((item) => {
    item.addEventListener('click', () => {
      if (item.classList.contains('disabled')) return;
      const target = item.dataset.view;
      if (target && views[target]) showView(target);
    });
  });

  // ---- Size hint (client-side only, never stored) ----
  function formatBytes(n) {
    if (n === 0) return '0 bytes';
    if (n === 1) return '1 byte';
    return n + ' bytes';
  }
  function updateSizeHint() {
    // Count UTF-8 bytes, not characters. This matches what would actually
    // be transmitted if/when a backend is wired up.
    const value = valueInput.value || '';
    const bytes = new TextEncoder().encode(value).length;
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

  // ---- Error display (inline, under form) ----
  function showError(msg) {
    errorMsg.textContent = msg || '';
  }

  // ---- Form submission ----
  function setSubmitting(isSubmitting) {
    submitBtn.disabled = isSubmitting;
    submitBtn.textContent = isSubmitting ? 'Saving…' : 'Save Secret';
  }

  form.addEventListener('submit', (e) => {
    e.preventDefault();
    showError('');

    const name = nameInput.value.trim();
    const value = valueInput.value; // do not trim — values may legitimately have leading/trailing spaces

    if (!name) {
      showError('Secret name is required.');
      nameInput.focus();
      return;
    }
    if (!/^[A-Za-z0-9_.-]+$/.test(name)) {
      showError('Name may only contain letters, digits, "_", "." and "-".');
      nameInput.focus();
      return;
    }
    if (!value) {
      showError('Secret value is required.');
      valueInput.focus();
      return;
    }
    if (secretExists(name)) {
      showError(`A secret named "${name}" already exists.`);
      nameInput.focus();
      nameInput.select();
      return;
    }

    setSubmitting(true);

    // Persist {name, value} only. No size field — size is client-side display only.
    const secrets = loadSecrets();
    secrets.push({ name, value });
    const ok = saveSecrets(secrets);

    setSubmitting(false);

    if (!ok) {
      showError('Failed to save. localStorage may be unavailable or full.');
      return;
    }

    // Success — clear form, keep view active, show transient success in error slot
    nameInput.value = '';
    valueInput.value = '';
    updateSizeHint();
    showError(`✓ Saved "${name}".`);
    // Fade the success message after a moment
    setTimeout(() => {
      if (errorMsg.textContent.startsWith('✓')) showError('');
    }, 2500);
    nameInput.focus();
  });
})();
