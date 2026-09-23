// Display helpers preserve unknown values. Only the backend owns the cart.
export const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
export function safeUrl(value) {
  if (typeof value !== 'string' || !value.trim()) return '';
  try {
    const url = new URL(value, 'http://localhost');
    return ['http:', 'https:'].includes(url.protocol) ? value : '';
  } catch { return ''; }
}
export function formatChatText(value) {
  const source = String(value ?? '');
  const plain = text => esc(text).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  const pattern = /\[([^\]\n]+)\]\(([^\s)]+)\)/g;
  let result = '', offset = 0;
  for (const match of source.matchAll(pattern)) {
    result += plain(source.slice(offset,match.index));
    const target = match[2];
    let allowed = /^https?:\/\//i.test(target) && !!safeUrl(target);
    if (target.startsWith('/') && !target.startsWith('//') && !target.includes('\\')) {
      try {
        const url = new URL(target,'https://ekt-chat.invalid');
        allowed = url.origin === 'https://ekt-chat.invalid' && (url.pathname.startsWith('/documents/') || url.pathname === '/api/purchase-terms');
      } catch { allowed = false; }
    }
    result += allowed ? `<a href="${esc(target)}" target="_blank" rel="noopener noreferrer">${plain(match[1])} ↗</a>` : plain(match[0]);
    offset = match.index + match[0].length;
  }
  return result + plain(source.slice(offset));
}
export const ATTACHMENT_ACCEPT = '.pdf,.xlsx,.xls,.docx,.jpeg,.jpg,.png';
export const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
export function attachmentError(file) {
  if (!file) return 'Выберите файл.';
  if (/\.doc$/i.test(file.name || '')) return 'Сохраните документ Word как DOCX или PDF и отправьте заново.';
  if (!/\.(pdf|xlsx|xls|docx|jpeg|jpg|png)$/i.test(file.name || '')) return 'Поддерживаются PDF, Excel XLS/XLSX, Word DOCX и фото JPG/PNG.';
  if (!file.size) return 'Файл пустой. Выберите другой файл.';
  if (file.size > MAX_ATTACHMENT_BYTES) return 'Размер файла не должен превышать 10 МБ.';
  return '';
}
export function certificatesForDisplay(product) {
  return (Array.isArray(product.certificates) ? product.certificates : []).flatMap(certificate => {
    if (!certificate || typeof certificate !== 'object') return [];
    const url = safeUrl(certificate.url);
    return url ? [{url, title: String(certificate.title || 'Сертификат'), isDemo: certificate.is_demo === true}] : [];
  });
}
export function money(value, currency) {
  if (value === null || value === undefined || !Number.isFinite(value)) return 'Цена уточняется';
  const number = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2}).format(value);
  return `${number} ${currency === 'KZT' ? '₸' : currency || '· валюта не указана'}`;
}
export function stockLabel(p) {
  if (p.stock === null || p.stock === undefined) return 'Наличие уточняется';
  const quantity = `${p.stock}${p.unit ? ' ' + p.unit : ''}`;
  if (p.requires_live_check) return `В снимке: ${quantity} · нужно уточнить`;
  return p.stock > 0 ? `Демо-остаток: ${quantity}` : 'Нет в демо-наличии';
}
export const canPropose = p => p?.can_add_to_cart === true && p.requires_live_check === false && Number.isFinite(p.stock) && p.stock > 0;
export const cartCount = cart => (cart?.items || []).reduce((sum, item) => sum + item.quantity, 0);
export function errorText(error) {
  const messages = {
    'Unknown session': 'Сессия завершилась после перезапуска сервера. Обновите страницу, чтобы начать новую.',
    'Proposal expired': 'Время подтверждения истекло. Выберите товар заново.',
    'Proposal is no longer pending': 'Это предложение уже закрыто. Выберите товар заново.',
    'Insufficient stock in demo catalog': 'Недостаточно остатка с учётом товаров в корзине.',
    'Unknown product': 'Товар не найден.',
    'Failed to fetch': 'Нет связи с сервером. Проверьте подключение и повторите действие.',
  };
  return messages[error.message] || error.message || 'Не удалось выполнить запрос. Повторите попытку.';
}
export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === 'string' ? detail : detail?.message || (Array.isArray(detail) ? 'Проверьте параметры запроса.' : 'Ошибка сервера'));
    this.status = status;
    this.detail = detail;
  }
}
export function createApi(fetcher = globalThis.fetch.bind(globalThis)) {
  async function request(path, method = 'GET', body) {
    const multipart = typeof FormData !== 'undefined' && body instanceof FormData;
    const response = await fetcher(path, {method, headers: body === undefined || multipart ? {} : {'Content-Type':'application/json'},
      ...(body === undefined ? {} : {body: multipart ? body : JSON.stringify(body)})});
    if (response.status === 204) return null;
    let data;
    try { data = await response.json(); } catch { throw new ApiError(response.status, 'Сервер вернул неверный ответ. Повторите попытку.'); }
    if (!response.ok) throw new ApiError(response.status, data.detail || data);
    return data;
  }
  const sessionPath = sid => `/api/sessions/${encodeURIComponent(sid)}`;
  const proposalPath = (sid, pid) => `${sessionPath(sid)}/cart/proposals/${encodeURIComponent(pid)}`;
  return {
    health: () => request('/health'),
    browse: (offset = 0) => request(`/api/products?limit=100&offset=${offset}`),
    search: query => request(`/api/products/search?q=${encodeURIComponent(query)}&limit=20`),
    product: id => request(`/api/products/${encodeURIComponent(id)}`),
    analogs: id => request(`/api/products/${encodeURIComponent(id)}/alternatives`),
    createSession: () => request('/api/sessions', 'POST'),
    history: sid => request(`${sessionPath(sid)}/messages`),
    chat: (sid, message, language = "ru") => request('/api/chat', 'POST', {session_id:sid, message, language}),
    attachment: (sid, file, message = '') => {
      const problem = attachmentError(file);
      if (problem) throw new Error(problem);
      if (message.length > 2000) throw new Error('Сократите сообщение до 2000 символов.');
      const form = new FormData();
      form.append('file', file, file.name);
      if (message.trim()) form.append('message', message.trim());
      return request(`${sessionPath(sid)}/attachments`, 'POST', form);
    },
    cart: sid => request(`${sessionPath(sid)}/cart`),
    propose: (sid, id, quantity) => {
      if (!Number.isInteger(quantity) || quantity < 1 || quantity > 1000) throw new Error('Количество должно быть целым числом от 1 до 1000.');
      return request(`${sessionPath(sid)}/cart/proposals`, 'POST', {product_id:id, quantity});
    },
    confirm: (sid, pid, confirmed) => {
      if (confirmed !== true) throw new Error('Нужно явное подтверждение добавления.');
      return request(`${proposalPath(sid, pid)}/confirm`, 'POST', {confirm:true});
    },
    cancel: (sid, pid) => request(proposalPath(sid, pid), 'DELETE'),
  };
}
