/* Standalone loader. Example: <script src="https://backend.example/embed.js"
   data-assistant-url="https://backend.example/" defer></script> */
(() => {
  'use strict';
  const loader = document.currentScript;
  if (!loader || document.getElementById('ekt-assistant-widget')) return;
  let assistant;
  try {
    assistant = new URL(loader.getAttribute('data-assistant-url'));
    if (!['http:', 'https:'].includes(assistant.protocol) || assistant.username || assistant.password) return;
  } catch { return; }
  assistant.searchParams.set('widget', '1');
  function mount() {
    if (document.getElementById('ekt-assistant-widget')) return;
    const host = document.createElement('div');
    host.id = 'ekt-assistant-widget';
    const root = host.attachShadow({mode:'open'});
    const css = document.createElement('style');
    css.textContent = `:host{all:initial;font:14px Arial,sans-serif;color:#252132;position:fixed;z-index:2147483000;right:max(20px,env(safe-area-inset-right));bottom:max(20px,env(safe-area-inset-bottom))}*{box-sizing:border-box}button,a{font:inherit}button{cursor:pointer}button:focus-visible,a:focus-visible{outline:3px solid #ba97ef;outline-offset:3px}.launcher{border:0;background:#8451d7;color:white;box-shadow:0 6px 25px #3c195b30;border-radius:16px;padding:16px 19px;display:flex;gap:9px;align-items:center;font-weight:bold;font-size:14px}.star{font-size:23px}.panel{position:absolute;right:0;bottom:0;width:420px;height:min(780px,calc(100dvh - 40px));max-width:calc(100vw - 40px);border:1px solid #dcd0ee;border-radius:18px;overflow:hidden;background:white;box-shadow:0 15px 70px #25142e35;display:flex;flex-direction:column}.panel[hidden],.launcher[hidden]{display:none}.bar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:7px 12px;background:#f5f0fb;border-bottom:1px solid #e8ddf4;flex-shrink:0}.bar a{color:#6133a9;text-decoration:none;font-size:12px}.close{width:34px;height:32px;border:0;background:transparent;border-radius:7px;font-size:26px;color:#6133a9}.close:hover{background:#eaddf8}iframe{width:100%;min-height:0;flex:1;border:0;display:block;background:white}@media(max-width:500px){:host{right:8px;bottom:max(8px,env(safe-area-inset-bottom))}.panel{width:calc(100vw - 16px);max-width:none;height:calc(100dvh - 16px - env(safe-area-inset-bottom));border-radius:14px}.launcher{padding:13px 15px;font-size:13px}}`;
    const launcher = document.createElement('button');
    launcher.type = 'button';
    launcher.className = 'launcher';
    launcher.textContent = '✦ EKT Ассистент';
    launcher.setAttribute('aria-expanded','false');
    launcher.setAttribute('aria-controls','ekt-chat-panel');
    const panel = document.createElement('section');
    panel.id = 'ekt-chat-panel';
    panel.className = 'panel';
    panel.hidden = true;
    panel.setAttribute('role','dialog');
    panel.setAttribute('aria-label','Каталожный ассистент EKT');
    panel.setAttribute('aria-modal','false');
    const bar = document.createElement('div');
    bar.className = 'bar';
    const full = document.createElement('a');
    full.href = assistant.href;
    full.target = '_blank';
    full.rel = 'noopener noreferrer';
    full.textContent = 'Открыть чат в отдельной вкладке ↗';
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'close';
    close.textContent = '×';
    close.setAttribute('aria-label','Закрыть ассистента');
    const frame = document.createElement('iframe');
    frame.title = 'EKT Ассистент: поиск товаров и демо-корзина';
    frame.referrerPolicy = 'no-referrer';
    frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox');
    bar.append(full,close);
    panel.append(bar,frame);
    root.append(css,launcher,panel);
    document.body.append(host);
    const setOpen = open => {
      panel.hidden = !open;
      launcher.hidden = open;
      launcher.setAttribute('aria-expanded',String(open));
      if (open && !frame.hasAttribute('src')) frame.src = assistant.href;
      (open ? close : launcher).focus();
    };
    launcher.addEventListener('click',() => setOpen(true));
    close.addEventListener('click',() => setOpen(false));
    root.addEventListener('keydown',event => {
      if (event.key === 'Escape' && !panel.hidden) { setOpen(false); event.preventDefault(); }
    });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded',mount,{once:true});
  else mount();
})();
