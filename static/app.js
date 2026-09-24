/**
 * Live Subtitles & Translation - Client Application (Sprint 1 Evolution)
 * Maneja WebSockets con reconexión automática, selector de matriz multilingüe (EN/ES/PT),
 * bypass de traducción para idiomas idénticos, y overlay optimizado para burn-in en OBS Studio.
 */

(function () {
  'use strict';

  // -------------------------------------------------------------------------
  // Elementos del DOM
  // -------------------------------------------------------------------------
  const elements = {
    body: document.body,
    statusDot: document.getElementById('status-dot'),
    statusText: document.getElementById('status-text'),
    selectSession: document.getElementById('select-session'),
    selectLangPair: document.getElementById('select-lang-pair'),
    lblPrefixSession: document.getElementById('lbl-prefix-session'),
    lblPrefixLang: document.getElementById('lbl-prefix-lang'),
    subtitlesContainer: document.getElementById('subtitles-container'),
    subtitlesList: document.getElementById('subtitles-list'),
    emptyState: document.getElementById('empty-state'),
    emptyTitle: document.getElementById('empty-title'),
    emptySubtitle: document.getElementById('empty-subtitle'),
    btnToggleSource: document.getElementById('btn-toggle-source'),
    lblSourceText: document.getElementById('lbl-source-text'),
    lblSourceState: document.getElementById('lbl-source-state'),
    btnToggleScroll: document.getElementById('btn-toggle-scroll'),
    lblScrollText: document.getElementById('lbl-scroll-text'),
    lblScrollState: document.getElementById('lbl-scroll-state'),
    btnResumeScroll: document.getElementById('btn-resume-scroll'),
    lblResumeScroll: document.getElementById('lbl-resume-scroll'),
    btnModeToggle: document.getElementById('btn-mode-toggle'),
    lblModeToggle: document.getElementById('lbl-mode-toggle'),
    btnFullscreenHome: document.getElementById('btn-fullscreen-home'),
    btnFullscreenTheme: document.getElementById('btn-fullscreen-theme'),
    btnCopyOverlay: document.getElementById('btn-copy-overlay'),
    lblCopyOverlay: document.getElementById('lbl-copy-overlay'),
    btnFontInc: document.getElementById('btn-font-inc'),
    btnFontDec: document.getElementById('btn-font-dec'),
    btnFullscreenFontInc: document.getElementById('btn-fullscreen-font-inc'),
    btnFullscreenFontDec: document.getElementById('btn-fullscreen-font-dec'),
    fontSizeControls: document.getElementById('font-size-controls'),
    btnScrollBottom: document.getElementById('btn-scroll-bottom'),
    btnToggleTheme: document.getElementById('btn-toggle-theme'),
    lblThemeState: document.getElementById('lbl-theme-state'),
    siteLangContainer: document.getElementById('site-lang-container'),
    selectSiteLang: document.getElementById('select-site-lang'),
    btnAdminSettings: document.getElementById('btn-admin-settings'),
    lblAdminSettings: document.getElementById('lbl-admin-settings'),
    authModal: document.getElementById('auth-modal'),
    authForm: document.getElementById('auth-form'),
    authKeyInput: document.getElementById('auth-key-input'),
    authErrorMsg: document.getElementById('auth-error-msg'),
    btnAuthClose: document.getElementById('btn-auth-close'),
    btnAuthCancel: document.getElementById('btn-auth-cancel'),
    lblAuthTitle: document.getElementById('lbl-auth-title'),
    lblAuthKey: document.getElementById('lbl-auth-key'),
    btnAuthSubmit: document.getElementById('btn-auth-submit'),
    toast: document.getElementById('toast'),
  };

  // -------------------------------------------------------------------------
  // Diccionario Internacionalizacion (i18n) - ES / EN / PT
  // -------------------------------------------------------------------------
  const I18N = {
    es: {
      siteTitle: 'Subtitulos en Vivo | Live Translation',
      sessionPrefix: 'Sesion',
      langPrefix: 'Idioma',
      sourceLabel: 'Lenguaje original:',
      scrollLabel: 'Auto-scroll:',
      themeLight: 'Modo Claro',
      themeDark: 'Modo Oscuro',
      themeTitle: 'Alternar entre modo claro y oscuro',
      sourceTitle: 'Mostrar u ocultar audio original',
      scrollTitle: 'Pausar o activar auto-scroll',
      scrollBottomTitle: 'Ir al final de la pagina',
      fontSizeTitle: 'Ajustar tamano de subtitulos',
      modeOverlay: 'Fullscreen',
      modeReader: 'Fullscreen',
      modeTitle: 'Alternar a Fullscreen',
      copyOverlay: 'Copiar Link OBS',
      copyOverlayTitle: 'Copiar URL optimizada para Browser Source en OBS Studio',
      adminSettings: 'Admin Settings',
      adminTitle: 'Panel de Control y Monitoreo',
      siteLangTitle: 'Idioma del sitio',
      emptyTitle: 'Esperando subtitulos de la transmision...',
      emptySubtitle: 'Las frases apareceran aqui en tiempo real segun el par de idiomas seleccionado.',
      newSubtitles: 'Nuevos subtitulos',
      toastCopied: 'URL de OBS copiada al portapapeles',
      toastCopyError: 'Error al copiar URL',
      authTitle: 'Acceso Administrativo',
      authKeyLabel: 'Access Key',
      authPlaceholder: '••••',
      authCancel: 'Cancelar',
      authEnter: 'Ingresar',
      authError: 'Access Key incorrecta',
      langPairs: {
        'en-es': 'EN -> ES',
        'es-es': 'ES -> ES (Nativo)',
        'es-en': 'ES -> EN',
        'en-pt': 'EN -> PT',
        'es-pt': 'ES -> PT',
        'all': 'Todos los canales'
      }
    },
    en: {
      siteTitle: 'Live Subtitles | Live Translation',
      sessionPrefix: 'Session',
      langPrefix: 'Language',
      sourceLabel: 'Original language:',
      scrollLabel: 'Auto-scroll:',
      themeLight: 'Light Mode',
      themeDark: 'Dark Mode',
      themeTitle: 'Toggle light and dark mode',
      sourceTitle: 'Show or hide original audio',
      scrollTitle: 'Pause or enable auto-scroll',
      scrollBottomTitle: 'Scroll to bottom',
      fontSizeTitle: 'Adjust subtitle font size',
      modeOverlay: 'Fullscreen',
      modeReader: 'Fullscreen',
      modeTitle: 'Toggle Fullscreen',
      copyOverlay: 'Copy OBS Link',
      copyOverlayTitle: 'Copy URL optimized for Browser Source in OBS Studio',
      adminSettings: 'Admin Settings',
      adminTitle: 'Control Room & Monitoring',
      siteLangTitle: 'Site language',
      emptyTitle: 'Waiting for live broadcast subtitles...',
      emptySubtitle: 'Sentences will appear here in real time according to the selected language pair.',
      newSubtitles: 'New subtitles',
      toastCopied: 'OBS URL copied to clipboard',
      toastCopyError: 'Error copying URL',
      authTitle: 'Admin Access',
      authKeyLabel: 'Access Key',
      authPlaceholder: '••••',
      authCancel: 'Cancel',
      authEnter: 'Enter',
      authError: 'Invalid Access Key',
      langPairs: {
        'en-es': 'EN -> ES',
        'es-es': 'ES -> ES (Native)',
        'es-en': 'ES -> EN',
        'en-pt': 'EN -> PT',
        'es-pt': 'ES -> PT',
        'all': 'All channels'
      }
    },
    pt: {
      siteTitle: 'Legendas ao Vivo | Live Translation',
      sessionPrefix: 'Sessao',
      langPrefix: 'Idioma',
      sourceLabel: 'Idioma original:',
      scrollLabel: 'Rolagem automatica:',
      themeLight: 'Modo Claro',
      themeDark: 'Modo Escuro',
      themeTitle: 'Alternar entre modo claro e escuro',
      sourceTitle: 'Mostrar ou ocultar audio original',
      scrollTitle: 'Pausar ou ativar rolagem automatica',
      scrollBottomTitle: 'Ir para o final',
      fontSizeTitle: 'Ajustar tamanho das legendas',
      modeOverlay: 'Fullscreen',
      modeReader: 'Fullscreen',
      modeTitle: 'Alternar para Fullscreen',
      copyOverlay: 'Copiar Link OBS',
      copyOverlayTitle: 'Copiar URL otimizada para Browser Source no OBS Studio',
      adminSettings: 'Admin Settings',
      adminTitle: 'Painel de Controle e Monitoramento',
      siteLangTitle: 'Idioma do site',
      emptyTitle: 'Aguardando legendas da transmissao...',
      emptySubtitle: 'As frases aparecerao aqui em tempo real de acordo com o par de idiomas selecionado.',
      newSubtitles: 'Novas legendas',
      toastCopied: 'URL do OBS copiada para a area de transferencia',
      toastCopyError: 'Erro ao copiar URL',
      authTitle: 'Acesso Administrativo',
      authKeyLabel: 'Access Key',
      authPlaceholder: '••••',
      authCancel: 'Cancelar',
      authEnter: 'Entrar',
      authError: 'Access Key incorreta',
      langPairs: {
        'en-es': 'EN -> ES',
        'es-es': 'ES -> ES (Nativo)',
        'es-en': 'ES -> EN',
        'en-pt': 'EN -> PT',
        'es-pt': 'ES -> PT',
        'all': 'Todos os canais'
      }
    }
  };

  // -------------------------------------------------------------------------
  // Configuración de Estado
  // -------------------------------------------------------------------------
  const urlParams = new URLSearchParams(window.location.search);
  const path = window.location.pathname;
  let isFullscreenMode = path.startsWith('/fullscreen') || path.startsWith('/overlay') || urlParams.get('mode') === 'fullscreen' || urlParams.get('mode') === 'overlay';
  let isOverlayMode = isFullscreenMode;
  let isObsTransparent = urlParams.get('transparent') === 'true' || urlParams.get('obs') === 'true';
  if (isObsTransparent && elements.body) {
    elements.body.classList.add('obs-transparent');
  }
  let currentSession = urlParams.get('session') || urlParams.get('session_id') || urlParams.get('room') || '';
  let rawLang = (urlParams.get('lang') || urlParams.get('pair') || localStorage.getItem('reader_lang') || 'es').toLowerCase();
  if (rawLang.includes('-')) {
    rawLang = rawLang.split('-')[1];
  }
  let currentUserLang = ['es', 'en', 'pt'].includes(rawLang) ? rawLang : 'es';
  let detectedSessionLang = 'en';
  let currentPair = currentUserLang;
  let isSubOnly = urlParams.get('subonly') === '1';

  let currentSiteLang = (localStorage.getItem('site_ui_lang') || 'es').toLowerCase();
  if (!['es', 'en', 'pt'].includes(currentSiteLang)) currentSiteLang = 'es';

  let isAutoScrollEnabled = true;
  let showSourceText = localStorage.getItem('subtitles_show_source') !== 'false';
  let subtitleFontSizeRem = parseFloat(localStorage.getItem('subtitles_font_size')) || 1.35;
  let fullscreenFontScale = parseFloat(localStorage.getItem('fullscreen_font_scale')) || 1.0;
  let currentTheme = localStorage.getItem('subtitles_theme') || 'dark';

  let ws = null;
  let reconnectTimer = null;
  let heartbeatTimer = null;
  let overlayFadeTimeout = null;

  const MAX_OVERLAY_ITEMS = 3;         // Máximo de frases visibles en OBS para no saturar
  const OVERLAY_FADE_DELAY_MS = 10000;   // Desvanecer tras 10s de inactividad
  const RECONNECT_INTERVAL_MS = 2500;    // Reintento de conexión cada 2.5s

  const LANG_LABELS = {
    es: 'Español',
    en: 'English',
    pt: 'Português'
  };

  function updateDetectedLanguageDefault(detectedLang) {
    if (!detectedLang) return;
    const norm = detectedLang.toLowerCase().trim();
    const mapped = (norm.startsWith('es') || norm === 'spanish') ? 'es' : ((norm.startsWith('pt') || norm === 'portuguese') ? 'pt' : 'en');
    detectedSessionLang = mapped;

    if (!elements.selectLangPair) return;
    Array.from(elements.selectLangPair.options).forEach(opt => {
      const baseName = LANG_LABELS[opt.value] || opt.value;
      if (opt.value === detectedSessionLang) {
        opt.textContent = `${baseName} (Default)`;
      } else {
        opt.textContent = baseName;
      }
    });
    autoResizeLangSelect();
  }

  function autoResizeLangSelect() {
    if (!elements.selectLangPair) return;
    const selectedOption = elements.selectLangPair.options[elements.selectLangPair.selectedIndex];
    const text = selectedOption ? selectedOption.text : 'Español';
    if (!autoResizeLangSelect.canvas) {
      autoResizeLangSelect.canvas = document.createElement('canvas');
    }
    const ctx = autoResizeLangSelect.canvas.getContext('2d');
    const computed = window.getComputedStyle(elements.selectLangPair);
    ctx.font = `${computed.fontWeight || '600'} ${computed.fontSize || '0.82rem'} ${computed.fontFamily || 'monospace'}`;
    const textWidth = ctx.measureText(text).width;
    // Ancho ajustado exactamente al texto visible + chevron + padding
    const targetWidth = Math.max(66, Math.ceil(textWidth + 34));
    elements.selectLangPair.style.width = `${targetWidth}px`;
  }

  function hasTranslationForItem(item, lang) {
    if (!item) return false;
    const l = (lang || currentUserLang || 'es').toLowerCase();
    if (item.translations && item.translations[l]) return true;
    if (item['text_' + l]) return true;
    if (l === (item.source_lang || 'en')) return true;
    return false;
  }

  function getTargetTextForItem(item, lang) {
    if (!item) return '';
    const l = (lang || currentUserLang || 'es').toLowerCase();
    if (item.translations && item.translations[l]) {
      return item.translations[l];
    }
    if (item['text_' + l]) {
      return item['text_' + l];
    }
    if (l === 'es' && item.text_target && (item.target_lang === 'es' || !item.target_lang)) return item.text_target;
    if (l === 'en' && item.text_source && (item.source_lang === 'en' || !item.source_lang)) return item.text_source;
    if (l === item.source_lang) return item.text_source || '';
    if (l === item.target_lang) return item.text_target || '';
    return item.text_target || item.text_source || '';
  }

  async function updateAllCardsLanguage() {
    const cards = Array.from(elements.subtitlesList.querySelectorAll('.subtitle-card'));
    const missingCards = [];
    const missingTexts = [];

    cards.forEach(card => {
      if (card._itemData) {
        const hasTrans = hasTranslationForItem(card._itemData, currentUserLang);
        const targetEl = card.querySelector('.subtitle-target');
        if (targetEl) {
          targetEl.textContent = getTargetTextForItem(card._itemData, currentUserLang);
        }
        const sourceEl = card.querySelector('.subtitle-source');
        if (sourceEl) {
          const sourceText = card._itemData.text_source || card._itemData.text_en;
          const currentTargetText = getTargetTextForItem(card._itemData, currentUserLang);
          if (sourceText && sourceText !== currentTargetText) {
            sourceEl.textContent = sourceText;
            sourceEl.style.display = '';
          } else {
            sourceEl.style.display = 'none';
          }
        }

        if (!hasTrans) {
          const textToTranslate = card._itemData.text_source || card._itemData.text_target || card._itemData.text_en || card._itemData.text_es || '';
          if (textToTranslate.trim()) {
            missingCards.push(card);
            missingTexts.push(textToTranslate.trim());
          }
        }
      }
    });

    if (missingTexts.length > 0) {
      const requestedLang = currentUserLang;
      try {
        const res = await fetch('/api/translate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            texts: missingTexts,
            target_lang: requestedLang
          })
        });
        if (res.ok) {
          const data = await res.json();
          const translations = data.translations || [];
          if (translations.length === missingCards.length && currentUserLang === requestedLang) {
            missingCards.forEach((card, idx) => {
              const transText = translations[idx];
              if (!card._itemData.translations) card._itemData.translations = {};
              card._itemData.translations[requestedLang] = transText;
              card._itemData['text_' + requestedLang] = transText;

              const targetEl = card.querySelector('.subtitle-target');
              if (targetEl) {
                targetEl.textContent = transText;
              }
              const sourceEl = card.querySelector('.subtitle-source');
              if (sourceEl) {
                const sourceText = card._itemData.text_source || card._itemData.text_en;
                if (sourceText && sourceText !== transText) {
                  sourceEl.textContent = sourceText;
                  sourceEl.style.display = '';
                } else {
                  sourceEl.style.display = 'none';
                }
              }
            });
          }
        }
      } catch (err) {
        console.warn('Error en traducción on-demand:', err);
      }
    }
  }

  // -------------------------------------------------------------------------
  // Inicialización de Modos Visuales, Selectores y Traducciones
  // -------------------------------------------------------------------------
  function applySiteTranslations() {
    const t = I18N[currentSiteLang] || I18N.es;

    if (elements.selectSiteLang) {
      elements.selectSiteLang.value = currentSiteLang;
    }

    if (!isOverlayMode) {
      document.title = t.siteTitle;
    }

    if (elements.lblPrefixSession) {
      const svg = elements.lblPrefixSession.querySelector('svg');
      elements.lblPrefixSession.textContent = t.sessionPrefix + ' ';
      if (svg) elements.lblPrefixSession.appendChild(svg);
    }

    if (elements.lblPrefixLang) {
      const svg = elements.lblPrefixLang.querySelector('svg');
      elements.lblPrefixLang.textContent = t.langPrefix + ' ';
      if (svg) elements.lblPrefixLang.appendChild(svg);
    }

    if (elements.selectLangPair) {
      elements.selectLangPair.value = currentUserLang;
      updateDetectedLanguageDefault(detectedSessionLang);
    }

    if (elements.lblSourceText) elements.lblSourceText.textContent = t.sourceLabel;
    if (elements.btnToggleSource) elements.btnToggleSource.title = t.sourceTitle;

    if (elements.lblScrollText) elements.lblScrollText.textContent = t.scrollLabel;
    if (elements.btnToggleScroll) elements.btnToggleScroll.title = t.scrollTitle;

    if (elements.btnScrollBottom) elements.btnScrollBottom.title = t.scrollBottomTitle;
    if (elements.fontSizeControls) elements.fontSizeControls.title = t.fontSizeTitle;

    if (elements.lblModeToggle) {
      elements.lblModeToggle.textContent = isOverlayMode ? t.modeReader : t.modeOverlay;
    }
    if (elements.btnModeToggle) elements.btnModeToggle.title = t.modeTitle;

    if (elements.lblCopyOverlay) elements.lblCopyOverlay.textContent = t.copyOverlay;
    if (elements.btnCopyOverlay) elements.btnCopyOverlay.title = t.copyOverlayTitle;

    if (elements.siteLangContainer) elements.siteLangContainer.title = t.siteLangTitle;
    if (elements.btnAdminSettings) {
      elements.btnAdminSettings.title = t.adminSettings;
      elements.btnAdminSettings.setAttribute('aria-label', t.adminSettings);
    }

    applyTheme();

    if (elements.emptyTitle) elements.emptyTitle.textContent = t.emptyTitle;
    if (elements.emptySubtitle) elements.emptySubtitle.textContent = t.emptySubtitle;

    if (elements.lblResumeScroll) elements.lblResumeScroll.textContent = t.newSubtitles;

    if (elements.lblAuthTitle) elements.lblAuthTitle.textContent = t.authTitle;
    if (elements.lblAuthKey) elements.lblAuthKey.textContent = t.authKeyLabel;
    if (elements.authKeyInput) elements.authKeyInput.placeholder = t.authPlaceholder;
    if (elements.btnAuthCancel) elements.btnAuthCancel.textContent = t.authCancel;
    if (elements.btnAuthSubmit) elements.btnAuthSubmit.textContent = t.authEnter;
  }

  function applyViewMode() {
    const t = I18N[currentSiteLang] || I18N.es;
    if (isFullscreenMode) {
      elements.body.classList.remove('mode-reader');
      elements.body.classList.add('mode-fullscreen');
      elements.body.classList.add('mode-overlay');
      document.title = 'Fullscreen | ' + t.siteTitle;
      if (elements.lblModeToggle) elements.lblModeToggle.textContent = t.modeReader || 'Lector';
    } else {
      elements.body.classList.remove('mode-fullscreen');
      elements.body.classList.remove('mode-overlay');
      elements.body.classList.add('mode-reader');
      document.title = t.siteTitle;
      if (elements.lblModeToggle) elements.lblModeToggle.textContent = 'Fullscreen';
    }

    if (isSubOnly) {
      elements.body.classList.add('hide-source');
    } else {
      updateSourceTextVisibility();
    }

    // Inicializar valor en el selector de idiomas
    if (elements.selectLangPair) {
      elements.selectLangPair.value = currentUserLang;
    }
  }

  function navigateToFullscreen() {
    const params = new URLSearchParams();
    if (currentSession) params.set('session', currentSession);
    if (currentUserLang) params.set('lang', currentUserLang);
    const qs = params.toString() ? '?' + params.toString() : '';
    window.location.href = '/fullscreen' + qs;
  }

  function navigateToReader() {
    const params = new URLSearchParams();
    if (currentSession) params.set('session', currentSession);
    if (currentUserLang) params.set('lang', currentUserLang);
    const qs = params.toString() ? '?' + params.toString() : '';
    window.location.href = '/' + qs;
  }

  function updateSourceTextVisibility() {
    if (showSourceText) {
      elements.body.classList.remove('hide-source');
      if (elements.lblSourceState) elements.lblSourceState.textContent = 'ON';
    } else {
      elements.body.classList.add('hide-source');
      if (elements.lblSourceState) elements.lblSourceState.textContent = 'OFF';
    }
    localStorage.setItem('subtitles_show_source', showSourceText);
  }

  // -------------------------------------------------------------------------
  // Gestión de WebSockets con Reconexión Automática
  // -------------------------------------------------------------------------
  function getWebSocketUrl() {
    const isSecure = window.location.protocol === 'https:';
    const protocol = isSecure ? 'wss:' : 'ws:';
    const host = window.location.host || 'localhost:8000';
    const sessionPath = currentSession ? `/${encodeURIComponent(currentSession)}` : '';
    return `${protocol}//${host}/ws${sessionPath}`;
  }

  function setStatus(state) {
    if (elements.statusDot) {
      elements.statusDot.className = 'status-dot ' + state;
    }
    if (elements.statusText) {
      if (state === 'connected') {
        elements.statusText.textContent = 'En vivo';
      } else if (state === 'reconnecting') {
        elements.statusText.textContent = 'Reconectando...';
      } else {
        elements.statusText.textContent = 'Desconectado';
      }
    }
  }

  function connectWebSocket() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }

    const wsUrl = getWebSocketUrl();
    setStatus('reconnecting');

    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('Error instanciando WebSocket:', e);
      scheduleReconnect();
      return;
    }

    ws.onopen = function () {
      setStatus('connected');
      console.log('[WS] Conectado a:', wsUrl);

      // Heartbeat periódico (ping cada 25s para mantener túnel Cloudflare activo)
      if (heartbeatTimer) clearInterval(heartbeatTimer);
      heartbeatTimer = setInterval(function () {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('ping');
        }
      }, 25000);
    };

    ws.onmessage = function (event) {
      try {
        if (event.data === 'pong') return;

        const payload = JSON.parse(event.data);
        handleIncomingMessage(payload);
      } catch (err) {
        console.error('Error procesando payload entrante:', err, event.data);
      }
    };

    ws.onclose = function (event) {
      console.warn('WebSocket cerrado (code:', event.code, '). Reintentando...');
      setStatus('reconnecting');
      cleanupSocket();
      scheduleReconnect();
    };

    ws.onerror = function (error) {
      console.error('Error en WebSocket:', error);
      setStatus('disconnected');
    };
  }

  function cleanupSocket() {
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer);
      heartbeatTimer = null;
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(function () {
      connectWebSocket();
    }, RECONNECT_INTERVAL_MS);
  }

  // -------------------------------------------------------------------------
  // Procesamiento de Mensajes y Renderizado con Deduplicación
  // -------------------------------------------------------------------------
  const seenSubtitleKeys = new Set();

  function getSubtitleKey(item) {
    const sid = item.session_id || 'default';
    const seq = item.seq != null ? item.seq : '';
    const ts = item.timestamp || '';
    const txt = (item.text_source || item.text_en || item.text_target || '').trim();
    return `${sid}:${seq}:${ts}:${txt}`;
  }

  function handleIncomingMessage(payload) {
    // 1. Caso: Historial Inicial ({ type: "history", data: [...] })
    if (Array.isArray(payload)) {
      renderHistory(payload);
      return;
    }
    if (payload.type === 'history' && Array.isArray(payload.data)) {
      renderHistory(payload.data);
      return;
    }

    if (payload.source_lang) {
      updateDetectedLanguageDefault(payload.source_lang);
    }

    // 2. Caso: Subtítulo individual en vivo
    const data = payload.data || payload;
    const textTarget = data.text_target || data.text_es || '';
    const textSource = data.text_source || data.text_en || '';

    // Filtrar duplicados estrictamente
    const key = getSubtitleKey(data);
    if (seenSubtitleKeys.has(key)) {
      return;
    }
    seenSubtitleKeys.add(key);
    if (seenSubtitleKeys.size > 800) {
      const oldest = seenSubtitleKeys.values().next().value;
      seenSubtitleKeys.delete(oldest);
    }

    if (textTarget || textSource || (data.translations && Object.keys(data.translations).length > 0)) {
      addSubtitleItem(data, true);
    }
  }

  function renderHistory(items) {
    if (!items || items.length === 0) return;

    // Limpiar lista antes de renderizar historial
    elements.subtitlesList.innerHTML = '';
    seenSubtitleKeys.clear();

    const itemsToRender = isObsTransparent ? items.slice(-MAX_OVERLAY_ITEMS) : items;

    itemsToRender.forEach(function (item) {
      const key = getSubtitleKey(item);
      seenSubtitleKeys.add(key);
      addSubtitleItem(item, false);
    });

    if (isAutoScrollEnabled) {
      scrollToBottom(false);
    }
  }

  function formatTime(isoString) {
    try {
      const date = new Date(isoString);
      if (isNaN(date.getTime())) return '';
      return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    } catch (e) {
      return '';
    }
  }

  function addSubtitleItem(item, isLive) {
    if (elements.emptyState) {
      elements.emptyState.style.display = 'none';
    }

    if (item.source_lang) {
      updateDetectedLanguageDefault(item.source_lang);
    }

    const card = document.createElement('article');
    card.className = 'subtitle-card';
    card._itemData = item;

    const formattedTime = formatTime(item.timestamp);
    const targetText = getTargetTextForItem(item, currentUserLang);
    const sourceText = item.text_source || item.text_en;

    // Meta & Latency Badge (con indicación de Bypass)
    const meta = document.createElement('div');
    meta.className = 'subtitle-meta';

    let latBadge = '';
    if (item.metrics && item.metrics.latency_ms) {
      const isBypass = item.metrics.bypass;
      const label = isBypass ? `BYPASS (${Math.round(item.metrics.latency_ms)}ms)` : `${Math.round(item.metrics.latency_ms)}ms`;
      const title = isBypass 
        ? `Transcripción nativa directa (Sin traducción LLM) | ASR: ${Math.round(item.metrics.asr_ms || 0)}ms` 
        : `Latencia E2E: ${Math.round(item.metrics.latency_ms)}ms (ASR: ${Math.round(item.metrics.asr_ms || 0)}ms | Trans: ${Math.round(item.metrics.trans_ms || 0)}ms)`;
      latBadge = `<span class="subtitle-latency" title="${title}">${label}</span>`;
    }

    meta.innerHTML = `<span class="subtitle-time">${formattedTime}</span>${latBadge}`;
    card.appendChild(meta);

    // Texto Principal (Idioma Destino / Target)
    const targetEl = document.createElement('p');
    targetEl.className = 'subtitle-target';
    targetEl.textContent = targetText;
    card.appendChild(targetEl);

    // Texto Secundario (Idioma Origen / Source)
    if (sourceText && sourceText !== targetText) {
      const sourceEl = document.createElement('p');
      sourceEl.className = 'subtitle-source';
      sourceEl.textContent = sourceText;
      card.appendChild(sourceEl);
    }

    elements.subtitlesList.appendChild(card);

    // Si el item entrante carece de la traducción al idioma seleccionado, traducirlo on-demand
    if (!hasTranslationForItem(item, currentUserLang)) {
      const textToTranslate = item.text_source || item.text_target || item.text_en || item.text_es || '';
      if (textToTranslate.trim()) {
        const langReq = currentUserLang;
        fetch('/api/translate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ texts: [textToTranslate.trim()], target_lang: langReq })
        })
          .then(res => res.json())
          .then(data => {
            if (data && data.translations && data.translations[0] && currentUserLang === langReq) {
              const transText = data.translations[0];
              if (!card._itemData.translations) card._itemData.translations = {};
              card._itemData.translations[langReq] = transText;
              card._itemData['text_' + langReq] = transText;
              targetEl.textContent = transText;
              if (sourceText && sourceText !== transText) {
                if (card.querySelector('.subtitle-source')) {
                  card.querySelector('.subtitle-source').textContent = sourceText;
                  card.querySelector('.subtitle-source').style.display = '';
                }
              } else {
                if (card.querySelector('.subtitle-source')) {
                  card.querySelector('.subtitle-source').style.display = 'none';
                }
              }
            }
          })
          .catch(() => {});
      }
    }

    // Limite preventivo en el DOM para evitar fugas de memoria tras dias de transmision continua
    const cards = elements.subtitlesList.querySelectorAll('.subtitle-card');
    if (cards.length > 500) {
      cards[0].remove();
    }

    // Modo Overlay OBS Transparente (solo si explicitamente se pasa ?obs=true o ?transparent=true)
    if (isObsTransparent) {
      trimOverlaySubtitles();
      resetOverlayFadeTimer();
    } else {
      // Modo Lector Web y Modo Fullscreen
      if (isAutoScrollEnabled) {
        requestAnimationFrame(function () {
          if (isAutoScrollEnabled) {
            scrollToBottom(true);
          }
        });
      } else if (isLive) {
        if (elements.btnResumeScroll) {
          elements.btnResumeScroll.classList.remove('hidden');
        }
      }
    }
  }

  function trimOverlaySubtitles() {
    if (!isObsTransparent) return;
    const cards = elements.subtitlesList.querySelectorAll('.subtitle-card');
    if (cards.length > MAX_OVERLAY_ITEMS) {
      const excess = cards.length - MAX_OVERLAY_ITEMS;
      for (let i = 0; i < excess; i++) {
        cards[i].remove();
      }
    }
  }

  function resetOverlayFadeTimer() {
    if (!isObsTransparent) return;

    const cards = elements.subtitlesList.querySelectorAll('.subtitle-card');
    cards.forEach(function (c) {
      c.classList.remove('fading-out');
    });

    if (overlayFadeTimeout) {
      clearTimeout(overlayFadeTimeout);
    }

    overlayFadeTimeout = setTimeout(function () {
      const currentCards = elements.subtitlesList.querySelectorAll('.subtitle-card');
      currentCards.forEach(function (c) {
        c.classList.add('fading-out');
      });
    }, OVERLAY_FADE_DELAY_MS);
  }

  // -------------------------------------------------------------------------
  // Auto-Scroll Robusto y Detección de Interacción del Usuario
  // -------------------------------------------------------------------------
  let isProgrammaticScroll = false;
  let programmaticScrollTimer = null;
  let userIsScrolling = false;
  let userScrollTimer = null;

  function markUserScrolling() {
    userIsScrolling = true;
    if (userScrollTimer) clearTimeout(userScrollTimer);
    userScrollTimer = setTimeout(function () {
      userIsScrolling = false;
    }, 1200);
  }

  function scrollToBottom(smooth) {
    if (!elements.subtitlesContainer) return;

    isProgrammaticScroll = true;
    if (programmaticScrollTimer) clearTimeout(programmaticScrollTimer);
    programmaticScrollTimer = setTimeout(function () {
      isProgrammaticScroll = false;
    }, 700);

    const container = elements.subtitlesContainer;
    const dist = container.scrollHeight - (container.scrollTop + container.clientHeight);
    const useSmooth = smooth && dist < 400;

    container.scrollTo({
      top: container.scrollHeight,
      behavior: useSmooth ? 'smooth' : 'auto'
    });

    if (elements.btnResumeScroll) {
      elements.btnResumeScroll.classList.add('hidden');
    }
  }

  function handleContainerScroll() {
    if (!elements.subtitlesContainer) return;

    // Si el scroll fue generado por animación programática y el usuario no está interactuando, nunca desactivar
    if (isProgrammaticScroll && !userIsScrolling) {
      return;
    }

    const { scrollTop, scrollHeight, clientHeight } = elements.subtitlesContainer;
    const distanceFromBottom = scrollHeight - (scrollTop + clientHeight);

    // Solo desactivar si el usuario está interactuando manualmente (rueda/touch) y se alejó del fondo
    if (distanceFromBottom > 160) {
      if (userIsScrolling) {
        if (isAutoScrollEnabled) {
          isAutoScrollEnabled = false;
          updateAutoScrollUI();
        }
        if (elements.btnResumeScroll) {
          elements.btnResumeScroll.classList.remove('hidden');
        }
      }
    } else if (distanceFromBottom <= 60) {
      // Si el usuario regresa cerca del fondo, reactivar auto-scroll
      if (!isAutoScrollEnabled) {
        isAutoScrollEnabled = true;
        updateAutoScrollUI();
      }
      if (elements.btnResumeScroll) {
        elements.btnResumeScroll.classList.add('hidden');
      }
    }
  }

  function updateAutoScrollUI() {
    if (!elements.lblScrollState) return;
    elements.lblScrollState.textContent = isAutoScrollEnabled ? 'ON' : 'PAUSADO';
    if (isAutoScrollEnabled) {
      elements.btnToggleScroll.classList.remove('inactive');
      elements.btnToggleScroll.classList.add('active');
    } else {
      elements.btnToggleScroll.classList.remove('active');
      elements.btnToggleScroll.classList.add('inactive');
    }
  }

  // -------------------------------------------------------------------------
  // Utilidades y Toast Feedback
  // -------------------------------------------------------------------------
  function showToast(message) {
    if (!elements.toast) return;
    elements.toast.textContent = message;
    elements.toast.classList.remove('hidden');
    setTimeout(function () {
      elements.toast.classList.add('hidden');
    }, 3500);
  }

  function promptFallback(url) {
    prompt('OBS Browser Source URL:', url);
  }

  function copyOverlayUrl() {
    const t = I18N[currentSiteLang] || I18N.es;
    const origin = window.location.origin;
    const langArg = currentUserLang ? `&lang=${encodeURIComponent(currentUserLang)}` : '';
    const sessionArg = currentSession && currentSession !== 'main' ? `&session=${encodeURIComponent(currentSession)}` : '';
    const overlayUrl = `${origin}/overlay?mode=overlay${sessionArg}${langArg}`;

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(overlayUrl).then(function () {
        showToast(t.toastCopied);
      }).catch(function () {
        promptFallback(overlayUrl);
      });
    } else {
      promptFallback(overlayUrl);
    }
  }

  function applySubtitleFontSize() {
    document.documentElement.style.setProperty('--subtitle-font-size', `${subtitleFontSizeRem}rem`);
    document.documentElement.style.setProperty('--subtitle-source-font-size', `${+(subtitleFontSizeRem * 0.7).toFixed(2)}rem`);
  }

  function adjustFontSize(delta) {
    subtitleFontSizeRem = Math.max(0.85, Math.min(2.5, +(subtitleFontSizeRem + delta).toFixed(2)));
    applySubtitleFontSize();
    localStorage.setItem('subtitles_font_size', subtitleFontSizeRem);
  }

  function applyFullscreenFontSize() {
    document.documentElement.style.setProperty(
      '--fullscreen-target-size',
      `calc(clamp(1.75rem, 3.2vw, 3rem) * ${fullscreenFontScale.toFixed(2)})`
    );
    document.documentElement.style.setProperty(
      '--fullscreen-source-size',
      `calc(clamp(1.05rem, 1.8vw, 1.6rem) * ${fullscreenFontScale.toFixed(2)})`
    );
  }

  function adjustFullscreenFontSize(delta) {
    fullscreenFontScale = Math.max(0.5, Math.min(2.5, +(fullscreenFontScale + delta).toFixed(2)));
    applyFullscreenFontSize();
    localStorage.setItem('fullscreen_font_scale', fullscreenFontScale);
  }

  const MOON_ICON_SVG = '<svg class="theme-icon icon-moon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';
  const SUN_ICON_SVG = '<svg class="theme-icon icon-sun" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>';

  function applyTheme() {
    const t = I18N[currentSiteLang] || I18N.es;
    if (currentTheme === 'light') {
      elements.body.classList.add('theme-light');
      if (elements.btnToggleTheme) {
        elements.btnToggleTheme.innerHTML = MOON_ICON_SVG;
        elements.btnToggleTheme.title = t.themeDark;
        elements.btnToggleTheme.setAttribute('aria-label', t.themeDark);
      }
      if (elements.btnFullscreenTheme) {
        elements.btnFullscreenTheme.innerHTML = MOON_ICON_SVG;
        elements.btnFullscreenTheme.title = t.themeDark;
        elements.btnFullscreenTheme.setAttribute('aria-label', t.themeDark);
      }
    } else {
      elements.body.classList.remove('theme-light');
      if (elements.btnToggleTheme) {
        elements.btnToggleTheme.innerHTML = SUN_ICON_SVG;
        elements.btnToggleTheme.title = t.themeLight;
        elements.btnToggleTheme.setAttribute('aria-label', t.themeLight);
      }
      if (elements.btnFullscreenTheme) {
        elements.btnFullscreenTheme.innerHTML = SUN_ICON_SVG;
        elements.btnFullscreenTheme.title = t.themeLight;
        elements.btnFullscreenTheme.setAttribute('aria-label', t.themeLight);
      }
    }
  }

  function toggleTheme() {
    currentTheme = currentTheme === 'light' ? 'dark' : 'light';
    localStorage.setItem('subtitles_theme', currentTheme);
    applyTheme();
  }

  // -------------------------------------------------------------------------
  // Modal de Autenticación para Admin Settings / Control Room
  // -------------------------------------------------------------------------
  function openAuthModal() {
    if (!elements.authModal) return;
    elements.authModal.classList.remove('hidden');
    if (elements.authErrorMsg) elements.authErrorMsg.classList.add('hidden');
    if (elements.authKeyInput) {
      elements.authKeyInput.value = '';
      setTimeout(function () {
        elements.authKeyInput.focus();
      }, 50);
    }
  }

  function closeAuthModal() {
    if (!elements.authModal) return;
    elements.authModal.classList.add('hidden');
    if (elements.authErrorMsg) elements.authErrorMsg.classList.add('hidden');
    if (elements.authKeyInput) elements.authKeyInput.value = '';
  }

  // -------------------------------------------------------------------------
  // Carga Dinámica de Salas / Sesiones desde la API
  // -------------------------------------------------------------------------
  async function loadAvailableSessions() {
    if (!elements.selectSession) return;
    try {
      const res = await fetch('/api/sessions');
      if (!res.ok) return;
      const data = await res.json();
      const sessions = data.sessions || [];
      elements.selectSession.innerHTML = '';
      if (sessions.length === 0) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = 'Sin sesiones';
        elements.selectSession.appendChild(opt);
        return;
      }

      if (!currentSession && sessions.length > 0) {
        currentSession = sessions[0].session_id.toLowerCase().trim();
      }

      const currentNorm = (currentSession || '').toLowerCase().trim();

      sessions.forEach(s => {
        const sid = (s.session_id || '').toLowerCase().trim();
        if (sid) {
          const opt = document.createElement('option');
          opt.value = sid;
          opt.textContent = s.title || ('Sala ' + sid.charAt(0).toUpperCase() + sid.slice(1));
          if (sid === currentNorm) opt.selected = true;
          elements.selectSession.appendChild(opt);
        }
      });
    } catch (e) {
      console.debug('Error al cargar sesiones:', e);
    }
  }

  // -------------------------------------------------------------------------
  // Listeners de Eventos
  // -------------------------------------------------------------------------
  function setupEventListeners() {
    // Cambio dinámico de sala / sesión
    if (elements.selectSession) {
      elements.selectSession.addEventListener('change', function (e) {
        currentSession = e.target.value;
        const url = new URL(window.location);
        url.searchParams.set('session', currentSession);
        window.history.replaceState({}, '', url);

        // Limpiar lista y reconectar a la nueva sesión
        elements.subtitlesList.innerHTML = '';
        if (elements.emptyState) elements.emptyState.style.display = 'flex';

        if (ws) {
          ws.close();
        }
        connectWebSocket();
      });
    }

    // Cambio dinámico de idioma de subtítulos (ES / EN / PT)
    if (elements.selectLangPair) {
      elements.selectLangPair.addEventListener('change', function (e) {
        currentUserLang = e.target.value;
        localStorage.setItem('reader_lang', currentUserLang);
        const url = new URL(window.location);
        url.searchParams.set('lang', currentUserLang);
        window.history.replaceState({}, '', url);

        // Redimensionar para ajustar al nuevo idioma y actualizar textos
        autoResizeLangSelect();
        updateAllCardsLanguage();
      });
    }

    // Alternar visibilidad de texto original
    if (elements.btnToggleSource) {
      elements.btnToggleSource.addEventListener('click', function () {
        showSourceText = !showSourceText;
        updateSourceTextVisibility();
      });
    }

    // Alternar Auto-Scroll
    if (elements.btnToggleScroll) {
      elements.btnToggleScroll.addEventListener('click', function () {
        isAutoScrollEnabled = !isAutoScrollEnabled;
        updateAutoScrollUI();
        if (isAutoScrollEnabled) scrollToBottom(true);
      });
    }

    // Botón flotante reanudar scroll
    if (elements.btnResumeScroll) {
      elements.btnResumeScroll.addEventListener('click', function () {
        isAutoScrollEnabled = true;
        updateAutoScrollUI();
        scrollToBottom(true);
      });
    }

    // Scroll manual y detección de interacción activa del usuario
    if (elements.subtitlesContainer) {
      elements.subtitlesContainer.addEventListener('scroll', handleContainerScroll, { passive: true });
      elements.subtitlesContainer.addEventListener('wheel', markUserScrolling, { passive: true });
      elements.subtitlesContainer.addEventListener('touchmove', markUserScrolling, { passive: true });
      elements.subtitlesContainer.addEventListener('pointerdown', markUserScrolling, { passive: true });
      elements.subtitlesContainer.addEventListener('keydown', markUserScrolling, { passive: true });
    }

    // Alternar a Modo Fullscreen con URL real (/fullscreen)
    if (elements.btnModeToggle) {
      elements.btnModeToggle.addEventListener('click', navigateToFullscreen);
    }

    // Copiar URL de OBS
    if (elements.btnCopyOverlay) {
      elements.btnCopyOverlay.addEventListener('click', copyOverlayUrl);
    }

    // Ajuste de fuente (Modo Lector)
    if (elements.btnFontInc) {
      elements.btnFontInc.addEventListener('click', function () { adjustFontSize(0.1); });
    }
    if (elements.btnFontDec) {
      elements.btnFontDec.addEventListener('click', function () { adjustFontSize(-0.1); });
    }
    // Ajuste de fuente independiente (Modo Fullscreen)
    if (elements.btnFullscreenFontInc) {
      elements.btnFullscreenFontInc.addEventListener('click', function () { adjustFullscreenFontSize(0.15); });
    }
    if (elements.btnFullscreenFontDec) {
      elements.btnFullscreenFontDec.addEventListener('click', function () { adjustFullscreenFontSize(-0.15); });
    }

    // Ir hacia abajo de todo (Boton V)
    if (elements.btnScrollBottom) {
      elements.btnScrollBottom.addEventListener('click', function () {
        scrollToBottom(true);
      });
    }

    // Alternar tema claro / oscuro
    if (elements.btnToggleTheme) {
      elements.btnToggleTheme.addEventListener('click', toggleTheme);
    }
    if (elements.btnFullscreenTheme) {
      elements.btnFullscreenTheme.addEventListener('click', toggleTheme);
    }

    // Controles de Fullscreen (Boton Home para volver al lector '/')
    if (elements.btnFullscreenHome) {
      elements.btnFullscreenHome.addEventListener('click', navigateToReader);
    }

    // Selector de Idioma del Sitio (ES / EN / PT)
    if (elements.selectSiteLang) {
      elements.selectSiteLang.addEventListener('change', function (e) {
        currentSiteLang = e.target.value;
        localStorage.setItem('site_ui_lang', currentSiteLang);
        applySiteTranslations();
      });
    }

    // Tuerca de Control Room (Redirige directamente a /controlroom)
    if (elements.btnAdminSettings) {
      elements.btnAdminSettings.addEventListener('click', function () {
        window.location.href = '/controlroom';
      });
    }
    if (elements.btnAuthClose) {
      elements.btnAuthClose.addEventListener('click', closeAuthModal);
    }
    if (elements.btnAuthCancel) {
      elements.btnAuthCancel.addEventListener('click', closeAuthModal);
    }
    if (elements.authModal) {
      elements.authModal.addEventListener('click', function (e) {
        if (e.target === elements.authModal) {
          closeAuthModal();
        }
      });
    }
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && elements.authModal && !elements.authModal.classList.contains('hidden')) {
        closeAuthModal();
      }
    });
    if (elements.authForm) {
      elements.authForm.addEventListener('submit', function (e) {
        e.preventDefault();
        const key = (elements.authKeyInput ? elements.authKeyInput.value : '').trim();
        if (key === '1234') {
          sessionStorage.setItem('control_room_authorized', 'true');
          window.location.href = '/controlroom';
        } else {
          if (elements.authErrorMsg) {
            const t = I18N[currentSiteLang] || I18N.es;
            elements.authErrorMsg.textContent = t.authError;
            elements.authErrorMsg.classList.remove('hidden');
          }
          if (elements.authKeyInput) {
            elements.authKeyInput.value = '';
            elements.authKeyInput.focus();
          }
        }
      });
    }
  }

  // -------------------------------------------------------------------------
  // Inicialización Global
  // -------------------------------------------------------------------------
  function init() {
    applySiteTranslations();
    applyTheme();
    applyViewMode();
    applySubtitleFontSize();
    applyFullscreenFontSize();
    autoResizeLangSelect();
    updateAutoScrollUI();
    setupEventListeners();
    loadAvailableSessions();
    window.addEventListener('focus', loadAvailableSessions);
    connectWebSocket();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
