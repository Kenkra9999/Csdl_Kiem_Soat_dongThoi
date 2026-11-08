'use strict';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const node = (tag, className = '', text = '') => {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = text;
  return item;
};
const icons = {
  users: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-3.9M15 3.1a4 4 0 0 1 0 7.8"/><circle cx="9" cy="7" r="4"/></svg>',
  hammer: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 9m-12-6 9 9M6 9l9 9M13 10 4 19m-2 3h13"/></svg>',
  trophy: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3h8v5a4 4 0 0 1-8 0V3ZM8 5H4v2c0 3 2 4 5 4m7-6h4v2c0 3-2 4-5 4m-3 1v7m-4 2h8m-7-2h6"/></svg>',
  replay: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 9h5M4 9V4m0 5 3-3a8 8 0 1 1-2 10"/></svg>',
  arrow: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14m-5-5 5 5-5 5"/></svg>',
};
const icon = name => { const holder = document.createElement('span'); holder.innerHTML = icons[name] || ''; return holder.firstElementChild || holder; };
const stateNames = { LIVE: 'Đang diễn ra', UPCOMING: 'Sắp mở', ENDED: 'Chờ chốt kết quả', CLOSED: 'Đã kết thúc' };
const kindNames = { ARTWORK: 'Nghệ thuật', COLLECTIBLE: 'Đồ sưu tầm', ELECTRONIC: 'Thiết bị điện tử' };
const checkNames = {
  cache_matches_history: 'Giá hiện tại khớp lịch sử', leader_matches_history: 'Người dẫn đầu chính xác',
  one_result_per_auction: 'Một kết quả cho mỗi phiên', closed_result_matches_winner: 'Kết quả khớp lượt thắng',
  unique_request_ids: 'Yêu cầu không bị trùng lặp', valid_bid_rules: 'Lượt trả giá đúng quy tắc',
  asset_subtypes_total_disjoint: 'Tài sản thuộc đúng lớp con', audit_atomicity: 'Nhật ký ghi nhận nguyên tử',
};
const app = { token: '', bootstrap: null, offset: 0, route: 'auctions', filters: { search: '', state: 'ALL', kind: 'ALL', sort: 'ending' }, items: [], listSignature: '', listBusy: false, listRequest: 0, detail: null, detailId: null, detailBusy: false, detailRequest: 0, resultsRequest: 0, resultsSignature: '', historyTab: 'bids', lastRequests: new Map(), inputDirty: false, mutationBusy: false, labLoaded: false, measurementsBusy: false, checksBusy: false, raceBusy: false, searchTimer: null };

function money(value, unit = true) {
  if (value === null || value === undefined || value === '') return '—';
  const str = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(str)) return '—';
  const [whole, fraction = ''] = str.split('.');
  const integer = BigInt(whole).toLocaleString('vi-VN');
  const decimals = fraction.slice(0, 2).replace(/0+$/, '');
  return integer + (decimals ? ',' + decimals : '') + (unit ? ' ₫' : '');
}
function localTime(value, full = false) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat('vi-VN', { timeZone: 'Asia/Ho_Chi_Minh', ...(full ? { year: 'numeric', month: '2-digit', day: '2-digit' } : { month: '2-digit', day: '2-digit' }), hour: '2-digit', minute: '2-digit', ...(full ? {} : { second: '2-digit' }) }).format(date);
}
function serverNow() { return Date.now() + app.offset; }
function syncTime(value) { if (value && !Number.isNaN(Date.parse(value))) app.offset = Date.parse(value) - Date.now(); }
function currentState(auction) {
  if (auction.status === 'CLOSED') return 'CLOSED';
  if (serverNow() < Date.parse(auction.opens_at)) return 'UPCOMING';
  if (serverNow() >= Date.parse(auction.closes_at)) return 'ENDED';
  return 'LIVE';
}
function illustration(auction) {
  if (auction.kind === 'ARTWORK') return Number(auction.asset_id) % 2 === 0 ? '/assets/autumn.svg' : '/assets/artwork.svg';
  if (auction.kind === 'COLLECTIBLE') return /tem|stamp/i.test(auction.title) ? '/assets/stamp.svg' : '/assets/coins.svg';
  return /ống kính|lens/i.test(auction.title) ? '/assets/lens.svg' : '/assets/camera.svg';
}
function badge(state) { return node('span', 'state-badge ' + state, stateNames[state] || state); }
function setConnection(ok) {
  const connection = $('#connection');
  connection.classList.toggle('offline', !ok);
  connection.lastElementChild.textContent = ok ? 'PostgreSQL đã kết nối' : 'Mất kết nối · Đang thử lại';
}
async function api(path, body) {
  const options = { method: body === undefined ? 'GET' : 'POST', headers: { Accept: 'application/json' }, cache: 'no-store' };
  if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.headers['X-Auction-Token'] = app.token; options.body = JSON.stringify(body); }
  let response;
  try { response = await fetch(path, options); } catch { setConnection(false); throw new Error('Chưa kết nối được máy chủ. Kiểm tra chương trình đang chạy rồi thử lại.'); }
  let payload;
  try { payload = await response.json(); } catch { throw new Error('Máy chủ trả về dữ liệu chưa hợp lệ. Vui lòng thử lại.'); }
  if (!response.ok || !payload.ok) { if (response.status >= 500) setConnection(false); throw new Error(payload.error?.message || 'Không thể thực hiện yêu cầu.'); }
  setConnection(true);
  if (payload.data?.server_time) syncTime(payload.data.server_time);
  return payload.data;
}
function toast(title, description = '', error = false) {
  const element = node('div', 'toast' + (error ? ' error' : ''));
  element.append(node('strong', '', title));
  if (description) element.append(node('span', '', description));
  $('#toast-container').append(element);
  setTimeout(() => element.remove(), 6000);
}
function renderEmpty(container, title, description, retry) {
  const box = node('div', retry ? 'error-state' : 'empty-state');
  box.append(node('span', 'empty-symbol', retry ? '↻' : '⌕'), node('h3', '', title), node('p', '', description));
  if (retry) { const button = node('button', 'button button-light', 'Thử lại'); button.type = 'button'; button.addEventListener('click', retry); box.append(button); }
  container.replaceChildren(box);
}
function renderSkeletons() {
  const grid = $('#auction-grid');
  for (let i = 0; i < 3; i++) { const card = node('div', 'skeleton-card'); card.setAttribute('aria-hidden', 'true'); card.append(node('div', 'skeleton skeleton-image'), node('div', 'skeleton skeleton-line'), node('div', 'skeleton skeleton-line short'), node('div', 'skeleton skeleton-line')); grid.append(card); }
}
function renderOverview(summary) {
  const section = $('#overview');
  const metrics = [['total_auctions', 'phiên đấu giá'], ['live_auctions', 'đang diễn ra'], ['total_bids', 'lượt trả giá']];
  metrics.forEach(([key, label], i) => { const cell = section.children[i]; cell.replaceChildren(node('strong', '', String(summary[key] ?? '—')), node('span', '', label)); });
}
async function loadBootstrap() {
  const data = await api('/api/bootstrap');
  app.bootstrap = data; app.token = data.csrf_token; syncTime(data.server_time); renderOverview(data.summary || {});
  return data;
}
function cardFor(auction) {
  const card = node('article', 'auction-card');
  const imageButton = node('button', 'card-image-button'); imageButton.type = 'button'; imageButton.setAttribute('aria-label', 'Xem phiên ' + auction.title);
  const image = node('img'); image.src = illustration(auction); image.alt = 'Minh họa ' + auction.title; image.loading = 'lazy'; image.decoding = 'async';
  const top = node('div', 'card-topline'); top.append(badge(currentState(auction)), node('span', 'card-number', 'PHIÊN #' + String(auction.id).padStart(3, '0')));
  imageButton.append(image, top); imageButton.addEventListener('click', () => openAuction(auction.id));
  const content = node('div', 'card-content'); content.append(node('div', 'asset-category', kindNames[auction.kind] || auction.category_name));
  const title = node('h3', 'card-title'); const titleButton = node('button', '', auction.title); titleButton.type = 'button'; titleButton.addEventListener('click', () => openAuction(auction.id)); title.append(titleButton); content.append(title);
  const hasBid = auction.current_price !== null;
  content.append(node('div', 'price-caption', auction.status === 'CLOSED' ? (auction.winning_price !== null ? 'Giá thắng cuộc' : 'Giá khởi điểm') : hasBid ? 'Giá cao nhất hiện tại' : 'Giá khởi điểm'));
  const price = node('div', 'card-price', money(auction.winning_price ?? auction.current_price ?? auction.start_price, false)); price.append(node('span', 'currency', '₫')); content.append(price);
  const meta = node('div', 'card-meta'); const bidCount = node('span'); bidCount.append(icon('hammer'), document.createTextNode((auction.bid_count ?? 0) + ' lượt trả giá'));
  const participants = node('span'); participants.append(icon('users'), document.createTextNode((auction.participant_count ?? 0) + ' người tham gia')); meta.append(bidCount, participants); content.append(meta);
  const bottom = node('div', 'card-bottom'); const clock = node('div', 'card-clock'); const countdown = node('span', 'countdown'); countdown.dataset.countdown = auction.closes_at; countdown.dataset.opens = auction.opens_at; countdown.dataset.status = auction.status; clock.append(countdown, node('span', 'countdown-label', ''));
  const button = node('button', 'card-action', currentState(auction) === 'LIVE' ? 'Tham gia trả giá' : 'Xem chi tiết'); button.type = 'button'; button.append(node('span', '', '↗')); button.addEventListener('click', () => openAuction(auction.id)); bottom.append(clock, button); content.append(bottom); card.append(imageButton, content); return card;
}
async function loadAuctions(silent = false) {
  const request = ++app.listRequest;
  app.listBusy = true;
  const grid = $('#auction-grid');
  if (!silent) grid.setAttribute('aria-busy', 'true');
  try {
    const query = new URLSearchParams(app.filters);
    const data = await api('/api/auctions?' + query.toString());
    if (request !== app.listRequest) return;
    const items = data.items || [];
    app.items = items;
    const signature = JSON.stringify(items);
    if (signature !== app.listSignature || !silent) {
      app.listSignature = signature;
      if (!items.length) renderEmpty(grid, 'Chưa tìm thấy phiên phù hợp', 'Thử thay đổi từ khóa hoặc chọn một trạng thái khác để khám phá thêm tài sản.');
      else grid.replaceChildren(...items.map(cardFor));
      updateCountdowns();
    }
    $('#result-count').textContent = items.length + ' phiên được tìm thấy';
  } catch (error) { if (request === app.listRequest && (!silent || !app.items.length)) renderEmpty(grid, 'Chưa tải được các phiên', error.message, () => loadAuctions()); }
  finally { if (request === app.listRequest) { app.listBusy = false; grid.setAttribute('aria-busy', 'false'); } }
}
function updateCountdowns() {
  $$('[data-countdown]').forEach(element => {
    const status = element.dataset.status;
    const closes = Date.parse(element.dataset.countdown); const opens = Date.parse(element.dataset.opens);
    const before = serverNow() < opens; const remaining = Math.max(0, Math.ceil(((before ? opens : closes) - serverNow()) / 1000));
    let text; let caption;
    if (status === 'CLOSED') { text = 'Đã chốt kết quả'; caption = localTime(element.dataset.countdown, true); }
    else if (!before && remaining === 0) { text = 'Đã hết thời gian'; caption = 'Chờ chốt kết quả'; }
    else { const d = Math.floor(remaining / 86400), h = Math.floor(remaining / 3600) % 24, m = Math.floor(remaining / 60) % 60, s = remaining % 60; text = d > 0 ? `${d} ngày ${String(h).padStart(2, '0')} giờ` : `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`; caption = before ? 'Còn lại đến giờ mở' : 'Thời gian còn lại'; }
    element.textContent = text;
    if (element.nextElementSibling?.classList.contains('countdown-label')) element.nextElementSibling.textContent = caption;
  });
  if (app.detail && $('#auction-dialog').open) updateDetailState(app.detail.auction);
}
function normalizeAmount(raw) {
  let text = raw.trim().replace(/\s/g, '').replace(/[₫đ]/gi, '');
  if (/^\d{1,3}(\.\d{3})+(,\d{1,2})?$/.test(text)) text = text.replace(/\./g, '').replace(',', '.');
  else text = text.replace(',', '.');
  if (!/^\d+(\.\d{1,2})?$/.test(text)) throw new Error('Nhập giá bằng số dương, tối đa 2 chữ số thập phân. Ví dụ: 1050000.');
  return text;
}
function createUUID() {
  if (crypto.randomUUID) return crypto.randomUUID();
  const values = crypto.getRandomValues(new Uint8Array(16)); values[6] = (values[6] & 15) | 64; values[8] = (values[8] & 63) | 128;
  const text = [...values].map(v => v.toString(16).padStart(2, '0')).join(''); return text.slice(0, 8) + '-' + text.slice(8, 12) + '-' + text.slice(12, 16) + '-' + text.slice(16, 20) + '-' + text.slice(20);
}
function appendFact(dl, title, value) { const cell = node('div'); cell.append(node('dt', '', title), node('dd', '', value)); dl.append(cell); }
function messageFor(result) {
  const names = {
    BID_ACCEPTED: ['Trả giá thành công', 'Lượt trả giá của bạn đã được ghi nhận trong phiên.'],
    BID_REPLAYED: ['Đã nhận diện yêu cầu gửi lại', 'Hệ thống trả lại lượt đã ghi nhận, không tạo thêm lượt trả giá.'],
    IDEMPOTENCY_CONFLICT: ['Mã yêu cầu đã được sử dụng', 'Mã này thuộc một nội dung khác. Hãy gửi một lượt trả giá mới.'],
    NOT_OPEN: ['Phiên đã kết thúc', 'Phiên không còn nhận lượt trả giá mới.'],
    NOT_STARTED: ['Phiên chưa mở', 'Bạn có thể tham gia khi thời gian mở phiên bắt đầu.'],
    AUCTION_ENDED: ['Đã hết thời gian trả giá', 'Yêu cầu được kiểm tra sau thời điểm đóng phiên.'],
    NOT_REGISTERED: ['Chưa đủ điều kiện tham gia', 'Người tham gia cần có đăng ký đã được duyệt ở phiên này.'],
    SELLER_CANNOT_BID: ['Người bán không thể tự trả giá', 'Vui lòng chọn một người tham gia khác.'],
    BID_TOO_LOW: ['Mức giá đã thay đổi', result.minimum ? 'Mức giá tối thiểu hiện tại là ' + money(result.minimum) + '.' : 'Giá trả cần cao hơn mức giá hiện tại theo đúng bước giá.'],
    INVALID_INCREMENT: ['Mức giá chưa đúng bước', 'Hãy chọn mức tối thiểu hoặc tăng theo bước giá đã công bố.'],
    INVALID_AMOUNT: ['Mức giá chưa hợp lệ', 'Giá phải là số dương, trong giới hạn và tối đa 2 chữ số thập phân.'],
    TOO_EARLY: ['Chưa đến giờ đóng phiên', 'Chỉ chốt kết quả khi đã hết thời gian nhận giá.'],
    AUCTION_CLOSED: ['Đã chốt kết quả', result.winning_price != null ? 'Giá thắng cuộc là ' + money(result.winning_price) + '.' : 'Phiên kết thúc và không có lượt trả giá hợp lệ.'],
    CLOSE_REPLAYED: ['Kết quả đã được chốt trước đó', 'Hệ thống giữ nguyên kết quả duy nhất của phiên.'],
    AUCTION_NOT_FOUND: ['Không tìm thấy phiên', 'Phiên đấu giá này không có trong hệ thống.'],
  };
  if (result.status === 'EXHAUSTED') return ['Chưa hoàn tất yêu cầu', 'Hệ thống đang có nhiều giao dịch cạnh tranh. Bạn có thể gửi lại yêu cầu.'];
  return names[result.code] || ['Yêu cầu chưa hoàn tất', 'Vui lòng kiểm tra thông tin và thử lại.'];
}
function showFormMessage(result) {
  const box = $('#bid-feedback'); if (!box) return;
  const [title, description] = messageFor(result);
  box.className = 'form-message' + (result.status === 'REJECTED' ? ' reject' : result.status === 'EXHAUSTED' ? ' error' : '');
  box.replaceChildren(node('strong', '', title), document.createTextNode(description));
  const metrics = [];
  if (result.bid_id) metrics.push('Lượt #' + result.bid_id);
  if (result.latency_ms !== undefined) metrics.push(Number(result.latency_ms).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' ms');
  if (result.retries !== undefined) metrics.push(result.retries + ' lần thử lại');
  if (metrics.length) box.append(node('small', '', metrics.join(' · ')));
  box.hidden = false;
}
function detailStructure(data) {
  const a = data.auction;
  const container = $('#detail-content');
  const grid = node('div', 'detail-grid');
  const visual = node('div', 'detail-visual'); const image = node('img'); image.src = illustration(a); image.alt = 'Minh họa tài sản: ' + a.title; visual.append(image);
  const description = node('section', 'detail-description'); description.append(node('h3', '', 'Về tài sản'), node('p', '', a.description || 'Tài sản trong bộ dữ liệu mô phỏng của đồ án đấu giá trực tuyến.'));
  const facts = node('dl', 'detail-facts'); appendFact(facts, 'Loại tài sản', kindNames[a.kind] || a.kind); appendFact(facts, 'Danh mục', a.category_name); appendFact(facts, 'Giá khởi điểm', money(a.start_price)); appendFact(facts, 'Bước giá', money(a.bid_step)); appendFact(facts, 'Mở phiên', localTime(a.opens_at, true)); appendFact(facts, 'Đóng phiên', localTime(a.closes_at, true)); description.append(facts); visual.append(description);
  const body = node('div', 'detail-body');
  const statusRow = node('div', 'detail-status-row'); const statusSlot = node('span'); statusSlot.id = 'detail-status'; statusSlot.append(badge(currentState(a))); statusRow.append(statusSlot, node('span', 'detail-lot', 'PHIÊN #' + String(a.id).padStart(3, '0'))); body.append(statusRow);
  const title = node('h2', '', a.title); title.id = 'detail-title'; body.append(title, node('p', 'seller-label', 'Người bán: ' + (a.seller_name || '—')));
  const priceBlock = node('div', 'detail-current-price'); const price = node('div'); const caption = node('div', 'detail-price-label'); caption.id = 'detail-price-label'; const value = node('div', 'detail-price-value'); value.id = 'detail-price'; price.append(caption, value);
  const clock = node('div', 'detail-countdown'); const timer = node('span', 'countdown'); timer.dataset.countdown = a.closes_at; timer.dataset.opens = a.opens_at; timer.dataset.status = a.status; timer.id = 'detail-timer'; clock.append(timer, node('span', 'countdown-label')); priceBlock.append(price, clock); body.append(priceBlock);
  const leader = node('div', 'leader-line'); leader.id = 'detail-leader'; body.append(leader);
  const winner = node('div', 'winner-panel'); winner.id = 'winner-panel'; winner.hidden = true; body.append(winner);
  const form = node('form', 'bid-form'); form.id = 'bid-form';
  const personLabel = node('label', '', 'Người tham gia'); personLabel.htmlFor = 'bidder-select'; const person = node('select'); person.id = 'bidder-select'; person.required = true;
  if (!data.participants?.length) { const option = node('option', '', 'Chưa có người tham gia được duyệt'); option.value = ''; person.append(option); }
  else data.participants.forEach(user => { const option = node('option', '', user.full_name); option.value = String(user.id); person.append(option); });
  const strategyLabel = node('label', '', 'Cơ chế kiểm soát đồng thời'); strategyLabel.htmlFor = 'bid-strategy'; const strategy = node('select'); strategy.id = 'bid-strategy';
  [['row_lock', 'Khóa dòng · READ COMMITTED'], ['serializable', 'SERIALIZABLE · Có thử lại']].forEach(([v, label]) => { const option = node('option', '', label); option.value = v; strategy.append(option); });
  try { strategy.value = localStorage.getItem('auction19_strategy') || 'row_lock'; } catch { /* Browser storage is optional. */ }
  strategy.addEventListener('change', () => { try { localStorage.setItem('auction19_strategy', strategy.value); } catch { /* No storage permission is needed. */ } });
  const amountLabel = node('label', '', 'Mức giá của bạn'); amountLabel.htmlFor = 'bid-amount';
  const amountRow = node('div', 'input-with-action'); const amount = node('input'); amount.id = 'bid-amount'; amount.type = 'text'; amount.inputMode = 'decimal'; amount.autocomplete = 'off'; amount.required = true; amount.setAttribute('aria-describedby', 'minimum-hint'); amount.addEventListener('input', () => app.inputDirty = true);
  const fillMinimum = node('button', '', 'Giá tối thiểu'); fillMinimum.type = 'button'; fillMinimum.addEventListener('click', () => { amount.value = app.detail.auction.minimum_bid; app.inputDirty = true; amount.focus(); }); amountRow.append(amount, fillMinimum);
  const hint = node('p', 'minimum-hint'); hint.id = 'minimum-hint';
  const submit = node('button', 'button button-primary full-width', 'Trả giá ngay'); submit.type = 'submit'; submit.id = 'submit-bid'; submit.append(icon('arrow'));
  form.append(personLabel, person, strategyLabel, strategy, amountLabel, amountRow, hint, submit);
  form.addEventListener('submit', submitBid);
  const replayRow = node('div', 'replay-row'); const replay = node('button', 'replay-button', 'Gửi lại yêu cầu vừa gửi'); replay.id = 'replay-bid'; replay.type = 'button'; replay.prepend(icon('replay')); replay.disabled = !app.lastRequests.has(a.id); replay.addEventListener('click', () => mutateBid(app.lastRequests.get(a.id))); replayRow.append(replay, node('span', 'price-unit-label', 'Đơn vị: VND')); form.append(replayRow);
  const simulation = node('p', 'simulation-note', 'Chọn danh tính mô phỏng trong danh sách đăng ký đã duyệt. Đây là môi trường học tập, không phải tài khoản đăng nhập thực.');
  const formNotice = node('div', 'closed-notice'); formNotice.id = 'closed-notice'; formNotice.hidden = true;
  const closeButton = node('button', 'button button-danger full-width', 'Chốt kết quả phiên'); closeButton.type = 'button'; closeButton.id = 'close-auction'; closeButton.hidden = true; closeButton.addEventListener('click', closeAuction);
  const feedback = node('div', 'form-message'); feedback.id = 'bid-feedback'; feedback.hidden = true; feedback.setAttribute('role', 'status');
  body.append(form, simulation, formNotice, closeButton, feedback); grid.append(visual, body);
  const history = node('section', 'detail-history'); const historyHeading = node('div', 'history-heading'); historyHeading.append(node('h3', '', 'Diễn biến phiên đấu giá')); const historyCount = node('span'); historyCount.id = 'history-count'; historyHeading.append(historyCount);
  const tabs = node('div', 'history-tabs'); tabs.setAttribute('role', 'group'); tabs.setAttribute('aria-label', 'Loại lịch sử');
  [['bids', 'Lịch sử trả giá'], ['audit', 'Nhật ký giao dịch']].forEach(([value, label]) => { const button = node('button', value === app.historyTab ? 'active' : '', label); button.type = 'button'; button.dataset.history = value; button.addEventListener('click', () => { app.historyTab = value; $$('[data-history]').forEach(b => b.classList.toggle('active', b.dataset.history === value)); renderHistory(app.detail); }); tabs.append(button); });
  const historyBody = node('div', 'history-body'); historyBody.id = 'history-body'; history.append(historyHeading, tabs, historyBody); container.replaceChildren(grid, history);
}
function updateDetailState(a) {
  const status = currentState(a); const stateElement = $('#detail-status'); if (!stateElement) return;
  if (stateElement.firstElementChild?.className !== 'state-badge ' + status) stateElement.replaceChildren(badge(status));
  const form = $('#bid-form'); const notice = $('#closed-notice'); const close = $('#close-auction');
  const canBid = status === 'LIVE' && (app.detail?.participants?.length || 0) > 0;
  $('#submit-bid').disabled = !canBid || app.mutationBusy;
  $('#bid-amount').disabled = !canBid || app.mutationBusy;
  $('#bidder-select').disabled = !canBid || app.mutationBusy;
  $('#bid-strategy').disabled = app.mutationBusy;
  $('#replay-bid').disabled = !app.lastRequests.has(a.id) || app.mutationBusy;
  close.hidden = status !== 'ENDED' && status !== 'CLOSED';
  close.disabled = app.mutationBusy;
  close.textContent = status === 'CLOSED' ? 'Xem lại kết quả đã chốt' : 'Chốt kết quả phiên';
  const notices = { UPCOMING: 'Phiên chưa mở. Bạn có thể theo dõi trước tài sản và thời gian bắt đầu.', ENDED: 'Đã hết thời gian nhận giá. Chốt phiên để xác định kết quả từ lịch sử đã ghi nhận.', CLOSED: a.winner_name ? 'Phiên đã kết thúc. Kết quả thắng được giữ nguyên khi chốt lại.' : 'Phiên kết thúc và không có người thắng.' };
  notice.hidden = canBid;
  if (!canBid) notice.textContent = notices[status] || 'Phiên chưa có đăng ký tham gia được duyệt.';
  form.classList.toggle('inactive-form', !canBid);
}
function updateDetail(data, first = false) {
  const a = data.auction; app.detail = data;
  if (first) { app.inputDirty = false; detailStructure(data); }
  $('#detail-price-label').textContent = a.status === 'CLOSED' && a.winning_price != null ? 'Giá thắng cuộc' : a.current_price != null ? 'Giá cao nhất hiện tại' : 'Giá khởi điểm';
  const price = $('#detail-price'); price.replaceChildren(document.createTextNode(money(a.winning_price ?? a.current_price ?? a.start_price, false)), node('span', 'currency', '₫'));
  const leader = $('#detail-leader'); leader.replaceChildren(icon('trophy'), document.createTextNode(a.leading_bidder_name ? 'Đang dẫn đầu: ' : 'Chưa có lượt trả giá. '));
  if (a.leading_bidder_name) leader.append(node('strong', '', a.leading_bidder_name));
  if (!a.leading_bidder_name) leader.append(node('span', '', 'Bạn có thể là người đầu tiên.'));
  const winner = $('#winner-panel'); winner.hidden = a.status !== 'CLOSED';
  if (a.status === 'CLOSED') winner.replaceChildren(node('h3', '', a.winner_name ? 'Người thắng cuộc' : 'Phiên không có người thắng'), node('p', '', a.winner_name ? a.winner_name + ' · ' + money(a.winning_price) : 'Không có lượt trả giá hợp lệ được ghi nhận trong phiên.'));
  $('#minimum-hint').textContent = 'Tối thiểu ' + money(a.minimum_bid) + ' · Bước giá ' + money(a.bid_step);
  const amount = $('#bid-amount'); if (first || (!app.inputDirty && document.activeElement !== amount)) amount.value = a.minimum_bid;
  $('#history-count').textContent = (a.bid_count ?? data.bids?.length ?? 0) + ' lượt trả giá · ' + (a.participant_count ?? data.participants?.length ?? 0) + ' người tham gia';
  const timer = $('#detail-timer'); timer.dataset.status = a.status; timer.dataset.countdown = a.closes_at; timer.dataset.opens = a.opens_at;
  updateDetailState(a); renderHistory(data); updateCountdowns();
}
function renderHistory(data) {
  const target = $('#history-body'); if (!target) return;
  if (app.historyTab === 'audit') {
    if (!data.audit?.length) { target.replaceChildren(node('div', 'history-empty', 'Chưa có giao dịch được ghi nhận.')); return; }
    target.replaceChildren(...data.audit.map(event => { const row = node('div', 'audit-row'); const body = node('div'); let label = event.action === 'BID_ACCEPTED' ? 'Ghi nhận lượt trả giá' : event.action === 'AUCTION_CLOSED' ? 'Chốt kết quả phiên' : event.action; if (event.actor_name) label += ' · ' + event.actor_name; if (event.details?.amount !== undefined) label += ' · ' + money(event.details.amount); body.append(node('div', 'audit-label', label), node('div', 'audit-time', localTime(event.occurred_at, true))); row.append(node('span', 'audit-point'), body); return row; }));
    return;
  }
  if (!data.bids?.length) { target.replaceChildren(node('div', 'history-empty', 'Lịch sử sẽ xuất hiện tại đây khi có lượt trả giá đầu tiên.')); return; }
  target.replaceChildren(...data.bids.map(bid => { const row = node('div', 'bid-row'); const initials = String(bid.bidder_name || 'NT').trim().split(/\s+/).slice(-2).map(p => p[0]).join('').toUpperCase(); const person = node('div'); person.append(node('div', 'bid-person', bid.bidder_name), node('div', 'bid-time', localTime(bid.accepted_at) + ' · Lượt #' + bid.id)); row.append(node('span', 'avatar', initials), person, node('div', 'bid-amount', money(bid.amount))); return row; }));
}
async function openAuction(id, fromRoute = false) {
  app.detailBusy = false;
  const request = ++app.detailRequest;
  const dialog = $('#auction-dialog'); const changed = app.detailId !== Number(id);
  app.detailId = Number(id); app.historyTab = changed ? 'bids' : app.historyTab;
  if (!dialog.open) { dialog.showModal(); document.body.classList.add('body-locked'); }
  if (!fromRoute && location.hash !== '#auction/' + id) history.pushState(null, '', '#auction/' + id);
  if (changed || !app.detail) $('#detail-content').replaceChildren(node('div', 'inline-spinner', 'Đang tải thông tin phiên…'));
  try { const data = await api('/api/auctions/' + id); if (request !== app.detailRequest || app.detailId !== Number(id) || !dialog.open) return; updateDetail(data, true); }
  catch (error) { if (request === app.detailRequest && app.detailId === Number(id)) renderEmpty($('#detail-content'), 'Chưa mở được phiên', error.message, () => openAuction(id)); }
}
async function refreshDetail(force = false) {
  if (!$('#auction-dialog').open || !app.detailId || (app.detailBusy && !force)) return;
  app.detailBusy = true; const id = app.detailId; const request = ++app.detailRequest;
  try { const data = await api('/api/auctions/' + id); if (request === app.detailRequest && app.detailId === id && $('#auction-dialog').open) updateDetail(data); }
  catch { /* A transient polling failure is reflected in the connection state. */ }
  finally { if (request === app.detailRequest) app.detailBusy = false; }
}
async function submitBid(event) {
  event.preventDefault(); if (app.mutationBusy || !app.detail) return;
  try {
    const payload = { bidder_id: Number($('#bidder-select').value), amount: normalizeAmount($('#bid-amount').value), request_id: createUUID(), strategy: $('#bid-strategy').value };
    if (!payload.bidder_id) throw new Error('Hãy chọn một người tham gia đã đăng ký.');
    await mutateBid(payload);
  } catch (error) { toast('Kiểm tra mức giá', error.message, true); }
}
async function mutateBid(payload) {
  if (!payload || app.mutationBusy || !app.detailId) return;
  const id = app.detailId; app.mutationBusy = true; ++app.detailRequest; app.detailBusy = false; app.lastRequests.set(id, { ...payload }); updateDetailState(app.detail.auction);
  const submit = $('#submit-bid'); if (submit) submit.textContent = 'Đang xử lý giao dịch…';
  try {
    const result = await api('/api/auctions/' + id + '/bids', payload);
    if (app.detailId === id) { showFormMessage(result); if (result.status === 'ACCEPTED') app.inputDirty = false; }
    const [title, description] = messageFor(result); toast(title, description, ['REJECTED', 'EXHAUSTED'].includes(result.status));
    await refreshDetail(true); await Promise.allSettled([loadBootstrap(), app.route === 'results' ? loadResults() : loadAuctions(true)]);
  } catch (error) { toast('Chưa hoàn tất lượt trả giá', error.message + ' Bạn có thể dùng nút gửi lại yêu cầu.', true); }
  finally { app.mutationBusy = false; if (app.detail && app.detailId === id && $('#auction-dialog').open) { $('#submit-bid').replaceChildren(document.createTextNode('Trả giá ngay'), icon('arrow')); updateDetailState(app.detail.auction); } }
}
async function closeAuction() {
  if (app.mutationBusy || !app.detailId) return;
  app.mutationBusy = true; ++app.detailRequest; app.detailBusy = false; const id = app.detailId; updateDetailState(app.detail.auction);
  try { const result = await api('/api/auctions/' + id + '/close', { strategy: $('#bid-strategy').value }); if (app.detailId === id && $('#auction-dialog').open) showFormMessage(result); const [title, description] = messageFor(result); toast(title, 'Phiên #' + id + ' · ' + description, result.status === 'REJECTED'); await refreshDetail(true); await Promise.allSettled([loadBootstrap(), loadAuctions(true)]); if (app.route === 'results') await loadResults(); }
  catch (error) { toast('Chưa chốt được phiên', error.message, true); }
  finally { app.mutationBusy = false; if (app.detail && $('#auction-dialog').open) updateDetailState(app.detail.auction); }
}
async function loadResults() {
  const request = ++app.resultsRequest;
  const list = $('#results-list');
  try {
    const data = await api('/api/auctions?state=CLOSED&sort=newest'); const items = data.items || [];
    if (request !== app.resultsRequest) return;
    const signature = JSON.stringify(items);
    if (signature === app.resultsSignature && list.children.length) return;
    app.resultsSignature = signature;
    const won = items.filter(a => a.winning_price !== null && a.winning_price !== undefined);
    const summary = $('#results-summary'); summary.replaceChildren();
    [[String(items.length), 'phiên đã kết thúc'], [String(won.length), 'phiên có người thắng'], [items.length ? (won.length / items.length * 100).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + '%' : '—', 'tỷ lệ phiên thành công']].forEach(([value, label]) => { const block = node('div', 'result-stat'); block.append(node('strong', '', value), node('span', '', label)); summary.append(block); });
    if (!items.length) { renderEmpty(list, 'Chưa có phiên được chốt', 'Kết quả sẽ xuất hiện tại đây khi một phiên được đóng sau thời điểm hết hạn.'); return; }
    list.replaceChildren(...items.map(a => { const row = node('article', 'result-row'); const image = node('img'); image.src = illustration(a); image.alt = 'Minh họa ' + a.title; image.loading = 'lazy'; const description = node('div', 'result-info'); description.append(badge('CLOSED'), node('h2', 'result-title', a.title)); const winner = node('div', 'result-winner'); winner.append(node('div', 'result-label', 'Người thắng'), node('div', 'result-value' + (!a.winner_name ? ' no-winner' : ''), a.winner_name || 'Không có người thắng')); const price = node('div', 'result-price-column'); price.append(node('div', 'result-label', 'Giá thắng cuộc'), node('div', 'result-price' + (!a.winning_price ? ' no-winner' : ''), a.winning_price != null ? money(a.winning_price) : 'Không có lượt trả giá')); const button = node('button', 'icon-button'); button.type = 'button'; button.setAttribute('aria-label', 'Xem kết quả ' + a.title); button.append(icon('arrow')); button.addEventListener('click', () => openAuction(a.id)); row.append(image, description, winner, price, button); return row; }));
  } catch (error) { if (request === app.resultsRequest) renderEmpty(list, 'Chưa tải được kết quả', error.message, loadResults); }
}
async function loadChecks() {
  if (app.checksBusy) return; app.checksBusy = true; $('#refresh-checks').disabled = true;
  try {
    const data = await api('/api/checks'); const checks = data.checks || []; const count = checks.filter(check => check.passed).length;
    const summary = node('div', 'integrity-status' + (count === checks.length && checks.length ? '' : ' fail')); const body = node('div'); body.append(node('strong', '', `${count}/${checks.length} điều kiện nhất quán được bảo đảm`), node('span', '', count === checks.length && checks.length ? 'Dữ liệu khớp với các quy tắc đã công bố.' : 'Một số điều kiện cần được kiểm tra lại.')); summary.append(node('div', 'integrity-check-icon', count === checks.length && checks.length ? '✓' : '!'), body); $('#integrity-summary').replaceChildren(summary);
    $('#checks-list').replaceChildren(...checks.map(check => { const row = node('div', 'check-row'); row.title = check.details; row.append(node('span', 'check-symbol' + (!check.passed ? ' fail' : ''), check.passed ? '✓' : '✕'), node('span', 'check-title', checkNames[check.check_name] || check.check_name)); return row; }));
    $('#checked-time').textContent = 'Kiểm tra lúc ' + localTime(data.checked_at, true) + ' · Di chuột vào từng điều kiện để xem chi tiết.';
  } catch (error) { renderEmpty($('#integrity-summary'), 'Chưa kiểm tra được dữ liệu', error.message, loadChecks); }
  finally { app.checksBusy = false; $('#refresh-checks').disabled = false; }
}
function mean(rows, key) { const nums = rows.map(row => Number(row[key])).filter(Number.isFinite); return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0; }
async function loadMeasurements() {
  if (app.measurementsBusy) return;
  app.measurementsBusy = true;
  try {
    const data = await api('/api/experiments/latest'); const tests = data.tests;
    if (tests && tests.tests_run !== undefined) { const badgeElement = node('div', 'test-badge'); const body = node('div'); body.append(node('p', '', tests.passed ? 'Kiểm thử tích hợp đã vượt qua' : 'Kiểm thử cần được kiểm tra lại'), node('small', '', `${tests.failures} lỗi kiểm thử · ${tests.errors} lỗi thực thi · ${tests.skipped} bỏ qua`)); badgeElement.append(node('strong', 'test-score', `${tests.tests_run - tests.failures - tests.errors - tests.skipped}/${tests.tests_run}`), body); $('#test-summary').replaceChildren(badgeElement); }
    const summaries = data.benchmark?.summaries || [];
    const cards = [];
    for (const strategy of ['row_lock', 'serializable']) {
      // Thẻ tổng hợp kịch bản "nhiều người cùng trả giá"; bản đo cũ không có trường scenario.
      const rows = summaries.filter(row => row.strategy === strategy && (!row.scenario || row.scenario === 'dong_thoi')); if (!rows.length) continue;
      const card = node('div', 'benchmark-card'); card.append(node('h3', '', strategy === 'row_lock' ? 'Khóa dòng' : 'SERIALIZABLE'));
      const dl = node('dl');
      const aggregate = [ ['Yêu cầu logic', String(rows.reduce((sum, r) => sum + Number(r.requests || 0), 0))], ['Độ trễ TB / yêu cầu', mean(rows, 'latency_mean_ms').toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' ms'], ['Tổng lần thử lại', String(rows.reduce((sum, r) => sum + Number(r.total_retries || 0), 0))], ['Bất biến dữ liệu', rows.every(r => r.invariants_passed) ? 'Đạt mọi vòng' : 'Cần kiểm tra'] ];
      aggregate.forEach(([label, value]) => dl.append(node('dt', '', label), node('dd', '', value))); card.append(dl); cards.push(card);
    }
    const comparison = node('div', 'benchmark-grid'); comparison.append(...cards); $('#benchmark-comparison').replaceChildren(comparison);
    $('#measurement-note').textContent = summaries.length ? 'Số đo đã lưu ngày ' + localTime(data.benchmark.measured_at_utc, true) + '. Kịch bản nhiều người cùng trả một mức giá; thời gian gồm chờ khóa, commit và retry (mỗi người giữ một kết nối). Bảng đủ 4 kịch bản ở mục 8 báo cáo.' : 'Chạy benchmark bằng công cụ kiểm thử để có số đo thực tế.';
    app.labLoaded = true;
  } catch (error) { $('#measurement-note').textContent = error.message; }
  finally { app.measurementsBusy = false; }
}
async function runRace(event) {
  event.preventDefault(); if (app.raceBusy) return;
  app.raceBusy = true; const button = $('#run-race'); button.disabled = true; button.textContent = 'Đang gửi các lượt trả giá…'; const output = $('#race-result'); output.replaceChildren(node('div', 'race-output', 'Các giao dịch đang được thực thi trên CSDL kiểm thử…'));
  try {
    const data = await api('/api/experiments/race', { strategy: $('#race-strategy').value, workers: Number($('#race-workers').value) });
    const box = node('div', 'race-output'); box.append(node('h3', '', 'Đã hoàn tất thực nghiệm'));
    const metrics = node('div', 'race-metrics'); [[data.accepted, 'được chấp nhận'], [data.rejected, 'bị từ chối'], [data.retries, 'lần thử lại']].forEach(([value, label]) => { const cell = node('div'); cell.append(node('strong', '', String(value ?? 0)), node('span', '', label)); metrics.append(cell); }); box.append(metrics);
    const checks = data.checks || []; box.append(node('div', 'race-check', checks.every(c => c.passed) && checks.length ? '✓ ' + checks.length + '/' + checks.length + ' bất biến dữ liệu đều đạt' : 'Cần kiểm tra kết quả bất biến'));
    (data.results || []).forEach(result => { const row = node('div', 'race-person'); row.append(node('span', '', 'Người tham gia #' + result.bidder_id), node('strong', result.status === 'ACCEPTED' ? '' : 'reject-label', result.status === 'ACCEPTED' ? 'Được ghi nhận' : result.status === 'REJECTED' ? 'Bị từ chối' : result.status)); box.append(row); });
    box.append(node('p', '', 'Phiên #' + data.auction_id + ' · ' + data.database + ' · ' + Number(data.latency_ms || 0).toLocaleString('vi-VN', { maximumFractionDigits: 1 }) + ' ms'), node('p', '', data.message || 'Các lượt cạnh tranh được kiểm tra trực tiếp bởi hàm trả giá PostgreSQL.'));
    output.replaceChildren(box); toast('Thực nghiệm đã hoàn tất', 'Xem lượt được ghi nhận và các điều kiện nhất quán bên dưới.');
  } catch (error) { output.replaceChildren(node('div', 'race-output error', error.message)); toast('Chưa hoàn tất thực nghiệm', error.message, true); }
  finally { app.raceBusy = false; button.disabled = false; button.replaceChildren(document.createTextNode('Chạy thực nghiệm'), node('span', '', '↗')); }
}
function setRoute() {
  const hash = location.hash.slice(1) || 'auctions';
  const detailMatch = hash.match(/^auction\/(\d+)$/);
  if (detailMatch) { if (!app.bootstrap) return; if ($('#page-auctions').hidden && app.route !== 'results') showPage('auctions'); openAuction(Number(detailMatch[1]), true); return; }
  if ($('#auction-dialog').open) $('#auction-dialog').close();
  const route = ['auctions', 'results', 'lab'].includes(hash) ? hash : 'auctions';
  showPage(route);
}
function showPage(route) {
  app.route = route; $$('.page').forEach(page => page.hidden = page.id !== 'page-' + route); $$('[data-route]').forEach(link => { link.classList.toggle('active', link.dataset.route === route); if (link.dataset.route === route) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current'); });
  document.title = ({ auctions: 'Phiên đấu giá', results: 'Kết quả đấu giá', lab: 'Kiểm soát đồng thời' })[route] + ' · Đấu Giá Việt';
  if (route === 'auctions') loadAuctions();
  if (route === 'results') loadResults();
  if (route === 'lab') { loadChecks(); if (!app.labLoaded) loadMeasurements(); }
}
function closeDialog() { $('#auction-dialog').close(); }
$('#close-dialog').addEventListener('click', closeDialog);
$('#auction-dialog').addEventListener('close', () => { document.body.classList.remove('body-locked'); if (location.hash.startsWith('#auction/')) history.replaceState(null, '', '#' + app.route); });
$('#auction-dialog').addEventListener('click', event => { if (event.target !== $('#auction-dialog')) return; const r = event.target.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) closeDialog(); });
$$('[data-state]').forEach(button => button.addEventListener('click', () => { app.filters.state = button.dataset.state; $$('[data-state]').forEach(b => b.classList.toggle('active', b === button)); loadAuctions(); }));
$('#search-input').addEventListener('input', event => { clearTimeout(app.searchTimer); const value = event.target.value; app.searchTimer = setTimeout(() => { app.filters.search = value; loadAuctions(); }, 230); });
$('#kind-filter').addEventListener('change', event => { app.filters.kind = event.target.value; loadAuctions(); });
$('#sort-filter').addEventListener('change', event => { app.filters.sort = event.target.value; loadAuctions(); });
$('#refresh-results').addEventListener('click', loadResults);
$('#refresh-checks').addEventListener('click', loadChecks);
$('#race-workers').addEventListener('input', event => $('#worker-value').textContent = event.target.value + ' người');
$('#race-form').addEventListener('submit', runRace);
window.addEventListener('hashchange', setRoute);
window.addEventListener('popstate', setRoute);
renderSkeletons();
(async () => { try { await loadBootstrap(); setRoute(); } catch (error) { setConnection(false); renderEmpty($('#auction-grid'), 'Chưa kết nối được dữ liệu', error.message, async () => { try { await loadBootstrap(); setRoute(); } catch (e) { toast('Chưa kết nối được dữ liệu', e.message, true); } }); } })();
setInterval(updateCountdowns, 1000);
setInterval(async () => { if (document.hidden || app.mutationBusy) return; try { if (!app.token) { await loadBootstrap(); setRoute(); return; } await loadBootstrap(); if ($('#auction-dialog').open) await refreshDetail(); if (app.route === 'auctions') await loadAuctions(true); else if (app.route === 'results') await loadResults(); } catch { /* Keep last known data visible while the server reconnects. */ } }, 4000);
