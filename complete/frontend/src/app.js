import {esc, safeUrl, money, stockLabel, canPropose, cartCount, errorText, createApi, ATTACHMENT_ACCEPT, attachmentError, certificatesForDisplay, formatChatText} from './core.js';

const $ = selector => document.querySelector(selector);
const api = createApi();
const widgetMode = new URLSearchParams(location.search).get('widget') === '1';
if (widgetMode) document.body.classList.add('widget-mode');
const state = {health:null, session:null, cart:{items:[], total_kzt:0}, catalog:[], results:[], products:new Map(),
  query:'', category:'all', all:false, searchError:'', searching:false, messages:[], pending:null,
  compare:[], chatOpen:widgetMode || innerWidth > 800, busy:false, draft:'', language:(['ru','kk','en'].includes(localStorage.getItem('ekt-language')) ? localStorage.getItem('ekt-language') : 'ru'), attachment:null, attachmentError:'', attachmentStatus:'', pendingBeforeAttachment:null};
let searchVersion = 0;
let searchTimer;
let storageKey;
const get = id => state.products.get(String(id));
const remember = products => products.forEach(p => state.products.set(String(p.id), p));
const price = p => money(p.price, p.currency);
const spec = p => Object.entries(p.properties || {}).map(([key,value]) => `${key}: ${value}`).slice(0,4).join(' · ') || 'Характеристики уточняются';
const isDemo = () => state.health?.catalog === 'demo';
const modeText = () => isDemo() ? 'Демо-каталог · вымышленные товары' : 'Каталог EKT · сохранённый снимок';
const productCountLabel = n => `${n} ${{one:'товар',few:'товара',many:'товаров',other:'товара'}[new Intl.PluralRules('ru').select(n)]}`;
const icon = name => {
  const paths = {search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',close:'<path d="m6 6 12 12M18 6 6 18"/>',compare:'<path d="M6 20V10M12 20V4M18 20V7"/>',attach:'<path d="m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9a2 2 0 0 1 3 3l-9 9a1 1 0 0 1-1-1l8-8"/>'};
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" aria-hidden="true">${paths[name] || ''}</svg>`;
};
function toast(text) {
  $('#toast').textContent = text;
  $('#toast').style.display = 'block';
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => $('#toast').style.display = 'none', 6500);
}
function fallbackImage(p) {
  const text = `${p.name} ${p.category}`.toLowerCase();
  return /кабел|провод/.test(text) ? '/assets/cable.jpg' : /ламп|led|свет/.test(text) ? '/assets/bulb.jpg' : /розет/.test(text) ? '/assets/socket.jpg' : '/assets/breaker.jpg';
}
function image(p, cls = '') {
  const src = safeUrl(p.image) || fallbackImage(p);
  return `<img class="${cls}" src="${esc(src)}" alt="${esc(p.name)}" loading="lazy" referrerpolicy="no-referrer">`;
}
document.addEventListener('error', event => {
  if (event.target instanceof HTMLImageElement) {
    event.target.hidden = true;
    const placeholder = document.createElement('span');
    placeholder.className = 'product-placeholder';
    placeholder.textContent = 'Фото недоступно';
    event.target.after(placeholder);
  }
}, true);
function formatText(text) {
  return formatChatText(text);
}
function sourceNote(p) {
  return p.data_mode === 'demo' ? 'Вымышленный товар для проверки корзины.' : 'Цена и остаток из снимка. Актуальность не подтверждена.';
}
function certificateLinks(p, showMissing = false) {
  const certificates = certificatesForDisplay(p);
  return certificates.length ? `<div class="certificate-links">${certificates.map(c => `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer">${esc(c.title)} ↗${c.isDemo ? '<span class="certificate-demo">Демо-документ</span>' : ''}</a>`).join('')}</div>` : showMissing ? '<p class="muted">Ссылки на сертификаты не предоставлены.</p>' : '';
}
function productCard(p, mini = false) {
  const id = esc(p.id);
  const conflict = p.data_conflicts?.length > 0 || p.match?.status === 'needs_review';
  const controls = `<div class="card-actions">${canPropose(p) ? `<button class="primary" data-action="stage" data-id="${id}">+ Добавить</button>` : ''}<button data-action="analogs" data-id="${id}">Аналоги</button></div>`;
  const details = `<div class="source-note">${esc(sourceNote(p))}</div>${conflict ? '<div class="conflict-note">Характеристики противоречат друг другу. Нужно уточнение.</div>' : ''}${p.reason ? `<div class="reason">${esc(p.reason)}<br>Взаимозаменяемость не подтверждена.</div>` : ''}${certificateLinks(p)}`;
  if (mini) return `<article class="mini-card">${image(p)}<h4>${esc(p.name)}</h4><div class="mini-meta">${esc(stockLabel(p))}</div><b>${esc(price(p))}</b>${details}${controls}<button class="text-button" data-action="detail" data-id="${id}">Подробнее ↗</button></article>`;
  return `<article class="product"><div class="product-art" data-caption="${p.image ? 'Фото из каталога' : 'Иллюстрация категории'}">${image(p)}<span class="stock ${p.requires_live_check ? 'unknown' : p.stock ? '' : 'sold'}">${esc(stockLabel(p))}</span><button class="compare-check ${state.compare.includes(p.id) ? 'selected' : ''}" data-action="compare-toggle" data-id="${id}" aria-pressed="${state.compare.includes(p.id)}" aria-label="Сравнить ${esc(p.name)}">${state.compare.includes(p.id) ? '✓' : icon('compare')}</button></div><small>${esc(p.sku)} · ${esc(p.brand || 'Бренд не указан')}</small><h3>${esc(p.name)}</h3><p>${esc(spec(p))}</p><div class="product-bottom"><b>${esc(price(p))}${p.unit ? `<small> / ${esc(p.unit)}</small>` : ''}</b></div>${details}${controls}<div class="product-tools"><button class="text-button" data-action="detail" data-id="${id}">Подробнее ↗</button><small>ID ${id}</small></div></article>`;
}
function render() {
  const draft = $('#chat-input')?.value;
  if (draft !== undefined) state.draft = draft;
  $('#app').innerHTML = `<header class="topbar"><a class="brand" href="/" aria-label="EKT, главная">ekt<span>●</span></a><span class="brand-caption">Электротехника<br>для ваших задач</span><form id="catalog-form" class="search-box">${icon('search')}<input id="catalog-search" type="search" maxlength="2000" value="${esc(state.query)}" placeholder="Название или артикул" aria-label="Поиск по каталогу"><button type="submit" aria-label="Найти товар">Найти</button></form><label class="language-picker" for="language-select">Язык <select id="language-select" aria-label="Язык ответа ассистента"><option value="ru" ${state.language === 'ru' ? 'selected' : ''}>Рус</option><option value="kk" ${state.language === 'kk' ? 'selected' : ''}>Қаз</option><option value="en" ${state.language === 'en' ? 'selected' : ''}>EN</option></select></label><button class="primary" data-action="cart" id="cart-button">Корзина · ${cartCount(state.cart)}</button></header>
  <main class="workspace ${state.chatOpen ? '' : 'collapsed'}"><section class="catalog"><div class="eyebrow">КАТАЛОГ / ЭЛЕКТРОТОВАРЫ</div><h1>Подберём то, что нужно<span class="accent">.</span></h1><p class="muted">Характеристики, наличие и сравнение — в одном окне.</p><div class="notice mode-banner">${isDemo() ? 'Режим демо: можно проверить добавление после подтверждения. Все товары и остатки вымышленные.' : 'Снимок EKT: дата актуальности, валюта и единица продажи не указаны. Для покупки нужно уточнить актуальные данные.'}</div><div class="tabs" role="group" aria-label="Категории">${[['all','Все товары'],['breaker','Автоматы'],['cable','Кабель'],['other','Остальные']].map(([id,label]) => `<button data-action="category" data-id="${id}" class="${state.category === id ? 'active' : ''}" aria-pressed="${state.category === id}">${label}</button>`).join('')}</div><div class="catalog-meta"><b>Подборка для вас</b><span id="catalog-count"></span></div><div id="products" class="product-grid"></div><div id="more"></div><div class="demo-note"><span>${esc(modeText())}</span><div class="footer-links"><button class="text-button" data-action="sources">О данных</button><button class="text-button" data-action="demo">Демо-сценарий</button></div></div></section>
  ${state.chatOpen ? `<aside class="assistant" aria-label="ИИ-ассистент"><div class="assistant-header"><span class="assistant-icon">✦</span><div><b>EKT Ассистент</b><div class="small status-line"><span class="status-dot"></span>Подключён к каталогу</div></div><button class="icon-button voice-button" data-action="listen" aria-label="Озвучить последний ответ" title="Озвучить последний ответ">🔊</button>${widgetMode ? '<button class="text-button widget-cart" data-action="cart" aria-label="Открыть корзину">Корзина</button>' : `<button class="icon-button" data-action="chat-close" aria-label="Свернуть чат">${icon('close')}</button>`}</div><div id="chat-body" class="chat-body" role="log" aria-live="polite"></div><form id="chat-form" class="composer"><div id="attachment-selection" class="attachment-selection" aria-live="polite"></div><div class="composer-row"><input id="chat-file" type="file" accept="${ATTACHMENT_ACCEPT}" class="file-input" tabindex="-1" aria-label="Выбрать документ или фото"><button class="attach-button icon-button" type="button" data-action="attach" aria-label="Прикрепить документ или фото" title="PDF, Excel, Word DOCX, JPG/PNG · до 10 МБ">${icon('attach')}</button><input id="chat-input" maxlength="2000" autocomplete="off" value="${esc(state.draft)}" placeholder="Спросите о товаре…" aria-label="Сообщение"><button class="primary" type="submit" aria-label="Отправить" ${state.busy ? 'disabled' : ''}>↑</button></div><div id="attachment-status" class="attachment-status" role="status"></div></form><div class="assistant-foot">PDF, Excel, Word DOCX, фото · до 10 МБ<br>В корзину — только после «Да, добавить»</div></aside>` : ''}</main>
  ${!state.chatOpen ? `<button class="primary assistant-launcher ${state.compare.length ? 'with-compare' : ''}" data-action="chat-open"><span>✦</span>EKT Ассистент</button>` : ''}
  ${state.compare.length ? `<div class="comparison-bar"><span>В сравнении: ${state.compare.length}</span><button data-action="comparison">Сравнить ↗</button><button class="icon-button" data-action="compare-clear" aria-label="Очистить сравнение">×</button></div>` : ''}`;
  renderProducts();
  renderChat();
}
function renderAttachment() {
  const selection = $('#attachment-selection');
  if (!selection) return;
  selection.innerHTML = state.attachment ? `<div class="selected-attachment"><span><b>${esc(state.attachment.name)}</b><small>${(state.attachment.size / 1024).toLocaleString('ru-RU', {maximumFractionDigits:0})} КБ</small></span><button type="button" class="icon-button" data-action="attachment-remove" aria-label="Убрать файл" ${state.busy ? 'disabled' : ''}>${icon('close')}</button></div><p class="attachment-hint">Текст документов разбирается на сервере; фото и сканы распознаются через OpenAI. Проверьте найденные позиции. Файл не добавляет товары в корзину.</p>` : '';
  const status = $('#attachment-status');
  status.classList.toggle('is-error', !!state.attachmentError);
  status.textContent = state.attachmentError || state.attachmentStatus;
  const submit = $('#chat-form button[type=submit]');
  submit.textContent = state.attachment ? 'Отправить файл' : '↑';
  submit.setAttribute('aria-label', state.attachment ? 'Отправить файл и сообщение' : 'Отправить');
  submit.disabled = state.busy;
  $('#chat-form [data-action=attach]').disabled = state.busy;
}
function category(p) {
  const text = `${p.name} ${p.category}`.toLowerCase();
  return /автомат|выключател/.test(text) ? 'breaker' : /кабел|провод/.test(text) ? 'cable' : 'other';
}
function renderProducts() {
  if (!$('#products')) return;
  const list = state.results.filter(p => state.category === 'all' || category(p) === state.category);
  $('#catalog-count').textContent = `${productCountLabel(list.length)}${state.query ? ' в выдаче' : ''} · ${isDemo() ? 'демо' : 'снимок'}`;
  $('#products').innerHTML = state.searching ? '<p class="loading">Ищем в каталоге…</p>' : state.searchError ? `<div class="error-panel">${esc(state.searchError)}</div>` : list.length ? (state.all ? list : list.slice(0,6)).map(p => productCard(p)).join('') : '<p class="empty-state">Товары не найдены. Попробуйте артикул или уточните параметры.</p>';
  $('#more').innerHTML = !state.searching && !state.searchError && list.length > 6 && !state.all ? '<button class="more" data-action="more">Показать все результаты</button>' : '';
}
function greeting() {
  const examples = isDemo() ? ['C16','DEMO-003','Условия доставки'] : ['Legrand 160A','аналоги 515290','Условия доставки'];
  return `<div class="chat-date">Ваш помощник по электротехнике</div><div class="greeting"><span class="star">✦</span><h2>Хороший выбор<br>начинается с вопроса</h2><p>Расскажите, что ищете. Найдём товар, посмотрим характеристики и сравним варианты.</p></div><div class="suggestions">${examples.map(q => `<button data-action="suggest" data-text="${esc(q)}">${esc(q)}<span>↗</span></button>`).join('')}</div><p class="privacy">Неизвестные данные уточняем, а не угадываем.</p>`;
}
function attachmentPreview(attachment) {
  if (!attachment) return '';
  const warnings = Array.isArray(attachment.warnings) ? attachment.warnings : [];
  return `<div class="attachment-result"><b>Файл: ${esc(attachment.filename)}</b>${warnings.length ? `<p class="attachment-hint">${esc(warnings.join(' '))}</p>` : ''}${attachment.text ? `<details><summary>Посмотреть распознанный текст</summary><pre>${esc(String(attachment.text).slice(0,5000))}</pre></details>` : ''}<p class="attachment-hint">Проверьте названия, артикулы и количество. В корзину из файла ничего не добавлено.</p></div>`;
}
function renderChat() {
  const body = $('#chat-body');
  if (!body) return;
  body.innerHTML = state.messages.length ? state.messages.map(m => `<div class="message ${m.role}">${m.role === 'bot' ? '<div class="bot-label">✦ EKT Ассистент</div>' : ''}<p>${formatText(m.text)}</p>${attachmentPreview(m.attachment)}${m.products?.length ? `<div class="response-grid">${m.products.map(p => productCard(p,true)).join('')}</div>` : ''}${m.cart ? '<button data-action="cart">Перейти в корзину ↗</button>' : ''}</div>`).join('') : greeting();
  if (state.pending) {
    const proposal = state.pending;
    const p = proposal.product;
    const fileNote = state.attachment ? 'Выбранный файл ещё не отправлен. Это подтверждение относится только к указанному ниже товару.' : state.pendingBeforeAttachment === proposal.proposal_id ? 'Это предложение подготовлено до разбора файла. Позиции из файла не выбраны для добавления.' : '';
    body.insertAdjacentHTML('beforeend', `<section class="confirmation" aria-label="Подтверждение добавления"><b>Подтвердите добавление</b>${fileNote ? `<p class="attachment-hint">${esc(fileNote)}</p>` : ''}<p class="selected-name">${esc(p.name)}</p><p>Количество: <strong>${proposal.quantity} ${esc(p.unit || '')}</strong><br>${esc(price(p))} × ${proposal.quantity} = <strong>${esc(money(p.price * proposal.quantity,p.currency))}</strong></p><div class="small">Действует до ${esc(new Date(proposal.expires_at).toLocaleTimeString('ru-RU'))}. Корзина пока не изменена.</div><div class="actions"><button class="primary" data-action="confirm" ${state.busy ? 'disabled' : ''}>Да, добавить</button><button data-action="cancel" ${state.busy ? 'disabled' : ''}>Отмена</button><button data-action="change-quantity" ${state.busy ? 'disabled' : ''}>Изменить количество</button></div></section>`);
  }
  if (state.busy) body.insertAdjacentHTML('beforeend', '<div class="loading" role="status">Обрабатываем запрос…</div>');
  body.scrollTop = body.scrollHeight;
  const submit = $('#chat-form button[type=submit]');
  if (submit) submit.disabled = state.busy;
  renderAttachment();
}
function say(text, products = [], cart = false) {
  remember(products);
  state.messages.push({role:'bot', text, products, cart});
  renderChat();
}
function ensureChat() {
  if (!state.chatOpen) { state.chatOpen = true; render(); }
}
function speakLatest() {
  const last = [...state.messages].reverse().find(message => message.role === 'bot');
  if (!last) { toast('Сначала получите ответ ассистента.'); return; }
  if (!('speechSynthesis' in window)) { toast('Озвучивание не поддерживается этим браузером.'); return; }
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(String(last.text).replace(/\[[^\]]+\]\([^)]*\)/g, ''));
  utterance.lang = {ru:'ru-RU', kk:'kk-KZ', en:'en-US'}[state.language] || 'ru-RU';
  utterance.rate = 0.95;
  window.speechSynthesis.speak(utterance);
}
async function cancelPending() {
  if (!state.pending) return;
  let wasClosed = false;
  try { await api.cancel(state.session, state.pending.proposal_id); }
  catch (error) {
    // A terminal proposal can safely disappear from the UI; a failed connection cannot.
    const closed = error.status === 409 && error.message === 'Proposal is no longer pending';
    const missing = error.status === 404 && error.message === 'Unknown proposal for this session';
    if (!closed && !missing) throw error;
    wasClosed = true;
  }
  state.pending = null;
  if (wasClosed) {
    state.cart = await api.cart(state.session);
    if ($('#cart-button')) $('#cart-button').textContent = `Корзина · ${cartCount(state.cart)}`;
  }
}
async function run(task) {
  if (state.busy) { toast('Дождитесь завершения текущего запроса.'); return; }
  state.busy = true;
  renderChat();
  try { await task(); }
  catch (error) { toast(errorText(error)); }
  finally { state.busy = false; renderChat(); }
}
async function send(message) {
  message = message.trim();
  if (!message || state.busy) return;
  ensureChat();
  state.messages.push({role:'user', text:message});
  await run(async () => {
    // A chat message never confirms a pending proposal; only the dedicated button can.
    const response = await api.chat(state.session, message, state.language);
    if (response.pending_action) {
      await cancelPending();
      state.pending = response.pending_action;
    }
    say(response.answer,response.products || []);
  });
}
async function sendAttachment(message) {
  if (!state.attachment || state.busy) return;
  const file = state.attachment;
  const problem = attachmentError(file);
  if (problem) { state.attachmentError = problem; renderAttachment(); return; }
  state.attachmentError = '';
  state.attachmentStatus = 'Загружаем и разбираем файл…';
  await run(async () => {
    try {
      const response = await api.attachment(state.session, file, message);
      // Extraction cannot prepare or confirm a cart proposal, even if a malformed response supplies one.
      state.pendingBeforeAttachment = state.pending?.proposal_id || null;
      const products = response.products || [];
      remember(products);
      state.messages.push({role:'user', text:`📎 ${file.name}${message.trim() ? '\n' + message.trim() : ''}`});
      state.messages.push({role:'bot', text:response.answer, products, attachment:response.attachment});
      state.attachment = null;
      state.draft = '';
      if ($('#chat-input')) $('#chat-input').value = '';
      state.attachmentStatus = 'Файл разобран. Проверьте найденные позиции в ответе.';
    } catch (error) {
      // Keep the File and message for an explicit retry after a connection or validation error.
      state.attachmentError = errorText(error);
      state.attachmentStatus = '';
    }
  });
}
async function search(query) {
  const version = ++searchVersion;
  state.query = query;
  state.searchError = '';
  state.searching = true;
  renderProducts();
  try {
    const response = query.trim() ? await api.search(query.trim()) : {products:state.catalog};
    if (version !== searchVersion) return;
    state.results = response.products;
    state.all = !!query.trim();
    remember(response.products);
  } catch (error) {
    if (version === searchVersion) { state.results = []; state.searchError = errorText(error); }
  } finally {
    if (version === searchVersion) { state.searching = false; renderProducts(); }
  }
}
function modal(title, content) {
  closeModal();
  const dialog = document.createElement('dialog');
  dialog.id = 'modal';
  dialog.setAttribute('aria-labelledby','modal-title');
  dialog.innerHTML = `<div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button class="icon-button" data-action="modal-close" aria-label="Закрыть окно">${icon('close')}</button></div><div class="modal-body">${content}</div>`;
  document.body.append(dialog);
  dialog.showModal();
}
function closeModal() { const dialog = $('#modal'); if (dialog) { dialog.close(); dialog.remove(); } }
const row = (key,value) => `<div class="spec-row"><span>${esc(key)}</span><b>${esc(value ?? 'Не указано')}</b></div>`;
function showQuantity(id, quantity = 1) {
  if (state.busy) return;
  const p = get(id);
  if (!p || !canPropose(p)) { toast('Для покупки нужно уточнить актуальные данные товара.'); return; }
  modal('Добавление в демо-корзину', `<h3>${esc(p.name)}</h3><p>${esc(price(p))}${p.unit ? ' / ' + esc(p.unit) : ''}</p><form id="quantity-form" data-id="${esc(id)}" class="dialog-form"><label>Количество <input name="quantity" type="number" min="1" max="1000" step="1" value="${quantity}" required aria-label="Количество для добавления"></label><div class="notice">Сначала проверим количество. Затем вы увидите товар и сумму для отдельного подтверждения.</div><button class="primary" type="submit">Проверить и продолжить</button></form>`);
}
async function stage(id, quantity) {
  await run(async () => {
    await cancelPending();
    const proposal = await api.propose(state.session,id,quantity);
    state.pending = proposal;
    remember([proposal.product]);
    closeModal();
    ensureChat();
  });
}
async function confirm() {
  if (!state.pending || state.busy) return;
  const pending = state.pending;
  await run(async () => {
    // Exactly one immutable proposal, and a separate, explicit click.
    try { state.cart = await api.confirm(state.session,pending.proposal_id,true); }
    catch (error) {
      if ((error.status === 409 && (['Proposal expired','Proposal is no longer pending'].includes(error.message) || error.detail?.code === 'proposal_changed')) || (error.status === 404 && error.message === 'Unknown proposal for this session')) state.pending = null;
      throw error;
    }
    state.pending = null;
    $('#cart-button').textContent = `Корзина · ${cartCount(state.cart)}`;
    say(`Добавлено: ${pending.product.name}, ${pending.quantity} ${pending.product.unit || ''}.`,[],true);
  });
}
async function showAnalogs(id) {
  await run(async () => {
    const p = get(id);
    const result = await api.analogs(id);
    closeModal();
    ensureChat();
    say(`Аналоги для «${p?.name || id}». ${result.note || ''}`,result.products || []);
  });
}
async function showDetail(id) {
  await run(async () => {
    const p = await api.product(id);
    remember([p]);
    const url = safeUrl(p.url);
    const warnings = (p.warnings || []).map(w => ({stock_not_provided:'Наличие не указано.',currency_not_provided:'Валюта не указана.',specifications_not_manufacturer_verified:'Характеристики не проверены по данным производителя.'}[w] || w));
    modal(p.name, `<div class="detail-top">${image(p,'detail-image')}<div><span class="badge">${esc(p.sku)} · ID ${esc(p.id)}</span><h3>${esc(p.name)}</h3><p>${esc(stockLabel(p))}</p><div class="price-large">${esc(price(p))}</div><div class="card-actions">${canPropose(p) ? `<button class="primary" data-action="stage" data-id="${esc(id)}">+ Добавить</button>` : ''}<button data-action="analogs" data-id="${esc(id)}">Показать аналоги</button></div></div></div><p class="source-note">${esc(sourceNote(p))}</p>${p.data_conflicts?.length ? '<div class="conflict-note">В источнике есть конфликт характеристик. Одно из значений нельзя считать подтверждённым.</div>' : ''}<h3>Характеристики</h3><div class="specs">${Object.entries(p.properties || {}).map(([key,value]) => row(key,value)).join('')}${row('Единица продажи',p.unit)}${row('Дата актуальности',p.source_as_of)}</div>${p.description ? `<p>${esc(p.description)}</p>` : ''}<h3>Склады и сертификаты</h3><p>${p.stores?.length ? esc(p.stores.map(s => `${s.name || s.store_name || 'Склад ' + (s.id || s.store_id)}: ${s.quantity ?? 'неизвестно'}`).join(' · ')) + ' (снимок)' : 'Данные по складам не предоставлены.'}</p>${certificateLinks(p,true)}${warnings.length ? `<p class="muted">${esc(warnings.join(' '))}</p>` : ''}${url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">Карточка на ekt.kz ↗</a>` : ''}`);
  });
}
async function showCart() {
  await run(async () => {
    state.cart = await api.cart(state.session);
    $('#cart-button').textContent = `Корзина · ${cartCount(state.cart)}`;
    const cart = state.cart;
    const cartUrl = safeUrl(cart.cart_url);
    modal('Ваша демо-корзина', cart.items.length ? `${cart.items.map(item => `<div class="cart-row">${image(item.product)}<div><h3>${esc(item.product.name)}</h3><p>${item.quantity} ${esc(item.product.unit || '')} × ${esc(price(item.product))}</p></div><b>${esc(money(item.subtotal_kzt,'KZT'))}</b></div>`).join('')}<div class="cart-total"><span>Итого</span><b>${esc(money(cart.total_kzt,'KZT'))}</b></div><p class="notice">Демонстрационная корзина. Заказ в ekt.kz не оформляется.</p>${cartUrl ? `<a class="primary cart-link" href="${esc(cartUrl)}" target="_blank" rel="noopener">Открыть страницу корзины ↗</a>` : ''}` : '<div class="empty-state">Корзина пока пуста. Выберите товар и подтвердите добавление.</div>');
  });
}
function showComparison() {
  const list = state.compare.map(get).filter(Boolean);
  const fields = [['Артикул',p=>p.sku],['Цена',price],['Наличие',stockLabel],['Характеристики',spec],['Источник',sourceNote]];
  modal('Сравнение товаров', `<div class="table-scroll"><table><thead><tr><th>Параметр</th>${list.map(p=>`<th>${esc(p.name)}</th>`).join('')}</tr></thead><tbody>${fields.map(([label,fn])=>`<tr><td>${esc(label)}</td>${list.map(p=>`<td>${esc(fn(p))}</td>`).join('')}</tr>`).join('')}</tbody></table></div><p class="notice">Совпадение отдельных параметров не подтверждает взаимозаменяемость.</p>`);
}
function showSources() {
  const unknown = state.catalog.filter(p => p.stock === null || p.stock === undefined).length;
  const count = productCountLabel(state.catalog.length);
  modal('О данных', `<p>${esc(modeText())}.</p><p>${isDemo() ? `${esc(count)}: товары, цены и остатки вымышленные и служат для демонстрации сценариев. Демо-сертификат показывает работу ссылки и не подтверждает качество реального изделия.` : `В подборке ${esc(count)}. У ${unknown} записей наличие не указано. Это не онлайн-проверка остатков; смотрите сведения об актуальности в карточке товара.`}</p><p>Ответы чата, поиск, аналоги и корзина обрабатываются сервером. Корзина меняется только после отдельного подтверждения. Фото без снимка конкретного товара подписаны как иллюстрации категории.</p><p>Вложение отправляется после нажатия «Отправить файл». Текст документов разбирается на сервере; фото и сканы распознаются через OpenAI. Распознанные позиции нужно проверить.</p>`);
}
function showDemo() {
  modal('Демо-сценарий', isDemo() ? '<ol><li>Спросите «DEMO-003»: товара нет, ассистент предложит DEMO-007 и объяснит сходство.</li><li>Спросите «Сертификат DEMO-004» и откройте ссылку на демо-документ.</li><li>Спросите «C16», нажмите «Добавить» и выберите количество 2. После «Проверить и продолжить» корзина ещё не меняется.</li><li>Нажмите «Да, добавить» и откройте корзину: добавлены 2 товара на 3 900 ₸.</li><li>Спросите «Условия доставки и минимальная партия». При желании прикрепите файл со списком товаров и проверьте найденные позиции.</li></ol><p>Товары, остатки, условия покупки и сертификат в этом режиме демонстрационные.</p>' : '<ol><li>Спросите «Legrand 160A» — получите карточку 515288.</li><li>Спросите «аналоги 515290» — сравните отключающую способность 18 и 25 кА.</li><li>Откройте «027228» — увидите предупреждение о конфликте характеристик.</li><li>Спросите «Условия доставки». Можно прикрепить файл со списком артикулов и проверить найденные позиции.</li></ol><p>Добавление и сценарий нулевого остатка показываются отдельно в режиме демо-корзины.</p>');
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const {action,id} = button.dataset;
  if (action === 'modal-close') { closeModal(); return; }
  if (action === 'chat-open') { ensureChat(); $('#chat-input')?.focus(); return; }
  if (action === 'chat-close') { state.chatOpen = false; render(); return; }
  if (action === 'listen') { speakLatest(); return; }
  if (action === 'category') { state.category = id; render(); return; }
  if (action === 'more') { state.all = true; renderProducts(); return; }
  if (action === 'compare-toggle') {
    if (state.compare.includes(id)) state.compare = state.compare.filter(value=>value!==id);
    else if (state.compare.length < 3) state.compare.push(id);
    else toast('Можно сравнить до трёх товаров.');
    render(); return;
  }
  if (action === 'compare-clear') { state.compare = []; render(); return; }
  if (action === 'comparison') { showComparison(); return; }
  if (action === 'sources') { showSources(); return; }
  if (action === 'demo') { showDemo(); return; }
  if (state.busy) { toast('Дождитесь завершения текущего запроса.'); return; }
  if (action === 'attach') { $('#chat-file')?.click(); return; }
  if (action === 'attachment-remove') { state.attachment = null; state.attachmentError = ''; state.attachmentStatus = ''; renderChat(); return; }
  if (action === 'suggest') void send(button.dataset.text);
  if (action === 'stage') showQuantity(id);
  if (action === 'detail') void showDetail(id);
  if (action === 'analogs') void showAnalogs(id);
  if (action === 'cart') void showCart();
  if (action === 'confirm') void confirm();
  if (action === 'cancel') void run(async()=>{ await cancelPending(); say('Предложение закрыто. Текущее содержимое можно посмотреть в корзине.',[],true); });
  if (action === 'change-quantity' && state.pending) showQuantity(state.pending.product_id,state.pending.quantity);
});
document.addEventListener('change', event => {
  if (event.target.id !== 'chat-file' || state.busy) return;
  const file = event.target.files?.[0];
  if (!file) return;
  state.attachmentError = attachmentError(file);
  state.attachment = state.attachmentError ? null : file;
  state.attachmentStatus = '';
  event.target.value = '';
  renderChat();
});
document.addEventListener('change', event => {
  if (event.target.id !== 'language-select') return;
  state.language = event.target.value;
  try { localStorage.setItem('ekt-language', state.language); } catch { /* preference is optional */ }
  toast({ru:'Язык ответа изменён.',kk:'Жауап тілі өзгертілді.',en:'Response language changed.'}[state.language]);
});
document.addEventListener('input', event => {
  if (event.target.id === 'catalog-search') {
    clearTimeout(searchTimer);
    const query = event.target.value;
    state.query = query;
    // Invalidate a previous request immediately, before debounce elapses.
    searchVersion++;
    searchTimer = setTimeout(()=>void search(query),350);
  }
});
document.addEventListener('submit', event => {
  if (event.target.id === 'chat-form') {
    event.preventDefault();
    if (state.busy) return;
    const input = $('#chat-input');
    const message = input.value;
    if (state.attachment) { state.draft = message; void sendAttachment(message); return; }
    state.attachmentError = ''; state.attachmentStatus = '';
    input.value = ''; state.draft = '';
    void send(message);
  }
  if (event.target.id === 'catalog-form') {
    event.preventDefault(); clearTimeout(searchTimer);
    void search($('#catalog-search').value);
  }
  if (event.target.id === 'quantity-form') {
    event.preventDefault();
    if (state.busy) return;
    const quantity = Number(new FormData(event.target).get('quantity'));
    void stage(event.target.dataset.id,quantity);
  }
});
async function start() {
  try {
    state.health = await api.health();
    storageKey = `ekt-server-session-v1:${state.health.catalog}`;
    try { state.session = sessionStorage.getItem(storageKey); } catch { /* storage may be disabled */ }
    if (state.session) {
      try { state.cart = await api.cart(state.session); }
      catch (error) { if (error.status === 404) state.session = null; else throw error; }
    }
    if (!state.session) {
      state.session = (await api.createSession()).session_id;
      try { sessionStorage.setItem(storageKey,state.session); } catch { /* server session still works */ }
      state.cart = await api.cart(state.session);
    }
    const history = await api.history(state.session);
    state.messages = (history.messages || []).filter(m => ['user','bot'].includes(m.role)).map(m => ({role:m.role,text:m.text,products:m.products || []}));
    state.messages.forEach(m => remember(m.products));
    const response = await api.browse();
    state.catalog = response.products;
    for (let offset = state.catalog.length; offset < response.total;) {
      const page = await api.browse(offset);
      if (!page.products.length) break;
      state.catalog.push(...page.products); offset += page.products.length;
    }
    state.results = state.catalog;
    remember(state.catalog);
    render();
  } catch (error) {
    $('#app').innerHTML = `<main class="workspace collapsed"><section class="catalog"><h1>Не удалось подключиться</h1><p class="error-panel">${esc(errorText(error))}</p><button class="primary" id="reload">Повторить подключение</button></section></main>`;
    $('#reload').addEventListener('click',()=>location.reload());
  }
}
void start();

