/* ─────────────────────────────────────────────
   AucFan リサーチツール フロントエンド
───────────────────────────────────────────── */

// ─── 状態管理 ───
const state = {
  isRunning: false,
  currentPage: 1,
  totalPages: 1,
  totalGroups: 0,
  filterStatus: '',
  filterKeyword: '',
  filterMinPrice: 0,
  filterMaxPrice: 99999,
  filterMinGroup: 1,
  refreshInterval: null,
  sseSource: null,
};

// ─── 初期化 ───
document.addEventListener('DOMContentLoaded', () => {
  startSSE();
  loadGroups();
  setInterval(loadGroups, 8000); // 8秒ごとに自動更新
});

// ─────────────────────────────────────────────
// SSE（リアルタイム進捗）
// ─────────────────────────────────────────────
function startSSE() {
  if (state.sseSource) state.sseSource.close();

  const sse = new EventSource('/api/stream');
  state.sseSource = sse;

  sse.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      updateProgressUI(data);
    } catch (err) {
      console.warn('SSEパースエラー', err);
    }
  };

  sse.onerror = () => {
    setTimeout(startSSE, 5000);
  };
}

function updateProgressUI(data) {
  const { progress, stats, is_running } = data;
  state.isRunning = is_running;

  // ヘッダーステータス
  const statusLabels = {
    idle: '待機中', scraping_list: '一覧取得中', scraping_detail: '詳細取得中',
    grouping: 'グループ化中', done: '完了', stopped: '停止済み', error: 'エラー',
  };
  const statusEl = document.getElementById('headerStatus');
  if (statusEl) {
    statusEl.textContent = statusLabels[progress.status] || progress.status;
    statusEl.style.background = is_running ? 'rgba(255,255,255,.35)' : 'rgba(255,255,255,.15)';
  }

  // 進捗バーセクション表示
  const progSection = document.getElementById('progressSection');
  const statsRow = document.getElementById('statsRow');
  if (progress.status !== 'idle') {
    if (progSection) progSection.style.display = '';
    if (statsRow) statsRow.style.display = '';
  }

  // 進捗バー
  const progLabel = document.getElementById('progressLabel');
  const progCount = document.getElementById('progressCount');
  const progBar = document.getElementById('progressBar');
  const progSub = document.getElementById('progressSub');

  if (progress.status === 'scraping_list') {
    const done = progress.pages_done || 0;
    const total = progress.total_pages || config_MAX_PAGES;
    const pct = total > 0 ? Math.min(100, Math.round(done / total * 100)) : 0;
    if (progLabel) progLabel.textContent = '一覧ページ取得中...';
    if (progCount) progCount.textContent = `${done}ページ / 約${config_MAX_PAGES}ページ`;
    if (progBar) progBar.style.width = pct + '%';
    if (progSub) progSub.textContent = `取得件数: ${progress.total_items || 0}件 | ${progress.keyword || ''}`;

  } else if (progress.status === 'scraping_detail') {
    const done = progress.detail_pages_done || 0;
    const total = progress.detail_pages_total || 1;
    const pct = total > 0 ? Math.min(100, Math.round(done / total * 100)) : 0;
    if (progLabel) progLabel.textContent = '詳細ページ取得中...';
    if (progCount) progCount.textContent = `${done}件 / ${total}件`;
    if (progBar) progBar.style.width = pct + '%';
    if (progSub) progSub.textContent = `候補: ${progress.candidates_found || 0}件`;

  } else if (progress.status === 'done') {
    if (progBar) progBar.style.width = '100%';
    if (progLabel) progLabel.textContent = '✅ 完了';
    if (progCount) progCount.textContent = `合計 ${progress.total_items || 0}件`;

  } else if (progress.status === 'grouping') {
    if (progLabel) progLabel.textContent = 'グループ化中...';
    if (progBar) progBar.style.width = '70%';
  }

  // ボタン状態
  const btnStart = document.getElementById('btnStart');
  const btnStop = document.getElementById('btnStop');
  if (btnStart) btnStart.disabled = is_running;
  if (btnStop) btnStop.disabled = !is_running;

  // 統計
  if (stats) {
    const byStatus = stats.by_status || {};
    setText('statTotal', stats.total || 0);
    setText('statCandidate', byStatus.candidate || 0);
    setText('statReview', byStatus.review || 0);
    setText('statOk', byStatus.ok || 0);
    setText('statNg', byStatus.ng || 0);
  }
}

// ─────────────────────────────────────────────
// スクレイピング制御
// ─────────────────────────────────────────────
const config_MAX_PAGES = 500; // サーバー設定と合わせる

async function startScraping() {
  const keyword = document.getElementById('inputKeyword').value.trim() || 'unknown';
  const res = await fetchJSON('/api/start', 'POST', { keyword, resume: false });
  if (res.success) {
    showToast(`スクレイピング開始: ${keyword}`);
    loadGroups();
  } else {
    showToast('❌ ' + (res.message || '開始失敗'), 'error');
  }
}

async function stopScraping() {
  const res = await fetchJSON('/api/stop', 'POST');
  if (res.success) showToast('停止リクエストを送りました');
}

// ─────────────────────────────────────────────
// 商品グループ取得・描画
// ─────────────────────────────────────────────
async function loadGroups(page) {
  if (page) state.currentPage = page;

  const params = new URLSearchParams({
    status: state.filterStatus,
    keyword: state.filterKeyword,
    min_price: state.filterMinPrice,
    max_price: state.filterMaxPrice,
    min_group: state.filterMinGroup,
    page: state.currentPage,
    per_page: 50,
  });

  const data = await fetchJSON(`/api/items?${params}`);
  if (!data || !data.groups) return;

  state.totalPages = data.total_pages || 1;
  state.totalGroups = data.total_groups || 0;

  renderGroups(data.groups);
  renderPagination();
  setText('groupsCount', `グループ: ${state.totalGroups}件`);
}

function renderGroups(groups) {
  const grid = document.getElementById('groupsGrid');
  const empty = document.getElementById('emptyState');

  if (!groups || groups.length === 0) {
    grid.innerHTML = '';
    if (empty) {
      empty.style.display = '';
      grid.appendChild(empty);
    }
    return;
  }

  if (empty) empty.style.display = 'none';
  grid.innerHTML = groups.map(g => renderGroupCard(g)).join('');
}

function renderGroupCard(group) {
  const statusClass = group.status || 'waiting';
  const statusLabel = {
    candidate: '仕入れ候補', waiting: '確認待ち', review: '要確認', ok: '✅ OK', ng: '❌ NG'
  }[statusClass] || statusClass;

  const countLabel = group.count > 1 ? `同一商品 <span class="group-badge">${group.count}件</span>` : '単品';

  // 画像HTML（最大5枚）
  const thumbs = group.items.slice(0, 5).map(item => {
    const thumb = item.thumbnail_local ? `/images/${getFilename(item.thumbnail_local)}` : '';
    if (thumb) {
      return `<img class="card-thumb" src="${thumb}" alt=""
                   onerror="this.outerHTML='<div class=card-thumb-placeholder>📦</div>'"
                   onclick="openItemDetail('${item.item_id}')">`;
    }
    return `<div class="card-thumb-placeholder">📦</div>`;
  }).join('');

  // 価格表示
  const firstItem = group.items[0];
  const price = firstItem.price || 0;
  const shipping = firstItem.shipping || 0;
  const total = firstItem.total || (price + shipping);

  // セラーID（最大5人）
  const sellerBadges = (group.seller_ids || []).slice(0, 5)
    .map(s => `<span class="seller-badge">${escHtml(s)}</span>`).join('');

  // アリプライス・Amazon検索URL
  const searchTitle = encodeURIComponent((group.title || '').substring(0, 50));
  const aliprice_url = `https://aliprice.com/search?q=${searchTitle}`;
  const amazon_url = `https://www.amazon.co.jp/s?k=${searchTitle}`;

  const groupId = group.group_id;
  const firstItemId = group.items[0].item_id;

  return `
  <div class="group-card status-${statusClass}" id="card-${groupId}">
    <div class="card-status-bar ${statusClass}">
      <span>${statusLabel}</span>
      <span>${countLabel}</span>
    </div>
    <div class="card-images">${thumbs}</div>
    <div class="card-body">
      <div class="card-title" onclick="openItemDetail('${firstItemId}')"
           title="${escHtml(group.title)}">${escHtml(group.title || '（タイトル取得中）')}</div>
      <div class="card-price-row">
        <div>
          <div class="card-price-label">合計</div>
          <div class="card-price">¥${total.toLocaleString()}</div>
        </div>
        <div class="card-price-sub">
          <div class="card-price-label">落札価格</div>
          <div class="price-val">¥${price.toLocaleString()}</div>
        </div>
        <div class="card-price-sub">
          <div class="card-price-label">送料</div>
          <div class="price-val">${shipping === 0 ? '無料' : '¥' + shipping.toLocaleString()}</div>
        </div>
      </div>
      <div class="card-sellers">出品者: ${sellerBadges || '—'}</div>
    </div>
    <div class="card-actions">
      <a class="btn btn-secondary btn-sm" href="${aliprice_url}" target="_blank" rel="noopener">
        🛒 AliPrice
      </a>
      <a class="btn btn-secondary btn-sm" href="${amazon_url}" target="_blank" rel="noopener">
        📦 Amazon
      </a>
      <button class="btn btn-success btn-sm" onclick="updateGroupStatus('${groupId}', 'ok')">
        ✅ OK
      </button>
      <button class="btn btn-danger btn-sm" onclick="updateGroupStatus('${groupId}', 'ng')">
        ❌ NG
      </button>
    </div>
  </div>`;
}

// ─────────────────────────────────────────────
// ステータス更新
// ─────────────────────────────────────────────
async function updateGroupStatus(groupId, status) {
  const res = await fetchJSON(`/api/group/${groupId}/status`, 'POST', { status });
  if (res.success) {
    showToast(`${res.updated}件を${status === 'ok' ? '✅ OK' : '❌ NG'}に更新しました`);
    loadGroups();
  }
}

// ─────────────────────────────────────────────
// 商品詳細モーダル
// ─────────────────────────────────────────────
async function openItemDetail(itemId) {
  const item = await fetchJSON(`/api/item/${itemId}`);
  if (!item) return;

  document.getElementById('itemModalTitle').textContent = item.title_full || item.title_short || '商品詳細';

  const searchTitle = encodeURIComponent((item.title_full || item.title_short || '').substring(0, 50));

  // 画像群
  const allImages = [item.thumbnail_local, ...(item.images_local || [])].filter(Boolean);
  const imagesHtml = allImages.length > 0
    ? `<div class="detail-images">${allImages.map(p =>
        `<img class="detail-img" src="/images/${getFilename(p)}"
              onerror="this.style.display='none'" alt="">`).join('')}</div>`
    : '<div class="detail-images"><div class="card-thumb-placeholder" style="width:120px;height:120px">📦</div></div>';

  document.getElementById('itemModalBody').innerHTML = `
    ${imagesHtml}
    <table class="detail-table">
      <tr><th>完全タイトル</th><td>${escHtml(item.title_full || item.title_short || '—')}</td></tr>
      <tr><th>落札価格</th><td>¥${(item.price||0).toLocaleString()}</td></tr>
      <tr><th>送料</th><td>${item.shipping === 0 ? '無料' : '¥' + (item.shipping||0).toLocaleString()}</td></tr>
      <tr><th>合計</th><td><strong>¥${(item.total||0).toLocaleString()}</strong></td></tr>
      <tr><th>セラーID</th><td>${escHtml(item.seller_id || '—')}</td></tr>
      <tr><th>グループ</th><td>${item.group_id ? `同一${item.group_size}件グループ` : '単品'}</td></tr>
      <tr><th>ステータス</th><td>${item.status || '—'}</td></tr>
      ${item.exclude_reason ? `<tr><th>除外理由</th><td style="color:var(--danger)">${escHtml(item.exclude_reason)}</td></tr>` : ''}
      ${item.size_info ? `<tr><th>サイズ</th><td>${escHtml(item.size_info)}</td></tr>` : ''}
    </table>
    <div class="detail-actions">
      <a class="btn btn-secondary" href="https://aliprice.com/search?q=${searchTitle}" target="_blank" rel="noopener">
        🛒 AliPriceで確認
      </a>
      <a class="btn btn-secondary" href="https://www.amazon.co.jp/s?k=${searchTitle}" target="_blank" rel="noopener">
        📦 Amazonで確認
      </a>
      ${item.url ? `<a class="btn btn-secondary" href="${item.url}" target="_blank" rel="noopener">🔗 元ページ</a>` : ''}
      <button class="btn btn-success" onclick="updateItemStatus('${item.item_id}', 'ok')">✅ OK</button>
      <button class="btn btn-danger" onclick="updateItemStatus('${item.item_id}', 'ng')">❌ NG</button>
    </div>
  `;

  document.getElementById('itemModal').style.display = 'flex';
}

async function updateItemStatus(itemId, status) {
  const res = await fetchJSON(`/api/item/${itemId}/status`, 'POST', { status, apply_group: true });
  if (res.success) {
    showToast(`ステータスを ${status} に更新しました`);
    hideModal('itemModal');
    loadGroups();
  }
}

// ─────────────────────────────────────────────
// フィルター
// ─────────────────────────────────────────────
let filterDebounce;
function applyFilter() {
  clearTimeout(filterDebounce);
  filterDebounce = setTimeout(() => {
    state.filterStatus = document.getElementById('filterStatus').value;
    state.filterKeyword = document.getElementById('filterKeyword').value;
    state.filterMinPrice = parseInt(document.getElementById('filterMinPrice').value) || 0;
    state.filterMaxPrice = parseInt(document.getElementById('filterMaxPrice').value) || 99999;
    state.filterMinGroup = parseInt(document.getElementById('filterMinGroup').value) || 1;
    state.currentPage = 1;
    loadGroups();
  }, 400);
}

function resetFilter() {
  document.getElementById('filterStatus').value = '';
  document.getElementById('filterKeyword').value = '';
  document.getElementById('filterMinPrice').value = 0;
  document.getElementById('filterMaxPrice').value = 99999;
  document.getElementById('filterMinGroup').value = 1;
  state.filterStatus = '';
  state.filterKeyword = '';
  state.filterMinPrice = 0;
  state.filterMaxPrice = 99999;
  state.filterMinGroup = 1;
  state.currentPage = 1;
  loadGroups();
}

// ─────────────────────────────────────────────
// CSV エクスポート
// ─────────────────────────────────────────────
function exportCsv() {
  window.location.href = '/api/export/csv';
  showToast('CSVをダウンロード中...');
}

// ─────────────────────────────────────────────
// セッション管理
// ─────────────────────────────────────────────
async function showSessions() {
  document.getElementById('sessionsModal').style.display = 'flex';
  document.getElementById('sessionsBody').innerHTML = '<div class="loading"><span class="spinner"></span>読み込み中...</div>';

  const data = await fetchJSON('/api/sessions');
  const sessions = data.sessions || [];

  if (sessions.length === 0) {
    document.getElementById('sessionsBody').innerHTML = '<p style="text-align:center;color:#6b7280;padding:30px">過去のセッションはありません</p>';
    return;
  }

  document.getElementById('sessionsBody').innerHTML = sessions.map(s => `
    <div class="session-item">
      <div class="session-info">
        <div class="session-name">${escHtml(s.name)}</div>
        <div class="session-meta">
          キーワード: ${escHtml(s.keyword || '—')} ／
          件数: ${s.total_items || 0}件 ／
          状態: ${s.status || '—'} ／
          更新: ${s.updated_at ? s.updated_at.substring(0, 16) : '—'}
        </div>
      </div>
      <button class="btn btn-primary btn-sm" onclick="loadSession('${escHtml(s.name)}')">ロード</button>
    </div>
  `).join('');
}

async function loadSession(sessionName) {
  const res = await fetchJSON(`/api/sessions/${sessionName}/load`, 'POST');
  if (res.success) {
    showToast(`セッション「${sessionName}」をロードしました（${res.total_items}件）`);
    hideModal('sessionsModal');
    loadGroups();
  } else {
    showToast('❌ ロード失敗', 'error');
  }
}

// ─────────────────────────────────────────────
// ページネーション
// ─────────────────────────────────────────────
function renderPagination() {
  const html = buildPaginationHTML();
  const el1 = document.getElementById('pagination');
  const el2 = document.getElementById('paginationBottom');
  if (el1) el1.innerHTML = html;
  if (el2) el2.innerHTML = html;
}

function buildPaginationHTML() {
  if (state.totalPages <= 1) return '';
  const cur = state.currentPage;
  const total = state.totalPages;

  let pages = [];
  // 常に1, 最後, 現在±2を表示
  const show = new Set([1, total, cur, cur-1, cur-2, cur+1, cur+2].filter(p => p >= 1 && p <= total));
  const sorted = [...show].sort((a, b) => a - b);

  let prev = 0;
  sorted.forEach(p => {
    if (prev && p - prev > 1) pages.push('...');
    pages.push(p);
    prev = p;
  });

  return pages.map(p => {
    if (p === '...') return `<span style="padding:5px 4px;color:#9ca3af">…</span>`;
    const active = p === cur ? 'active' : '';
    return `<button class="page-btn ${active}" onclick="loadGroups(${p})">${p}</button>`;
  }).join('');
}

// ─────────────────────────────────────────────
// モーダル
// ─────────────────────────────────────────────
function hideModal(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}

// ─────────────────────────────────────────────
// ユーティリティ
// ─────────────────────────────────────────────
async function fetchJSON(url, method = 'GET', body = null) {
  try {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(url, opts);
    return await res.json();
  } catch (err) {
    console.warn('fetchエラー', url, err);
    return {};
  }
}

function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function escHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function getFilename(path) {
  if (!path) return '';
  return path.split('/').pop().split('\\').pop();
}

// ─────────────────────────────────────────────
// 分析レポート
// ─────────────────────────────────────────────
async function showReport() {
  document.getElementById('reportModal').style.display = 'flex';
  document.getElementById('reportBody').innerHTML = '<div class="loading">分析中...</div>';

  try {
    const res = await fetch('/api/report');
    if (!res.ok) {
      const err = await res.json();
      document.getElementById('reportBody').innerHTML = `<p style="color:red">${err.error || 'エラーが発生しました'}</p>`;
      return;
    }
    const data = await res.json();
    document.getElementById('reportBody').innerHTML = renderReport(data);
  } catch (e) {
    document.getElementById('reportBody').innerHTML = `<p style="color:red">通信エラー: ${e}</p>`;
  }
}

function renderReport(data) {
  const fmt = (n) => n ? n.toLocaleString() + '円' : '-';

  // ── セラーランキング ──
  let sellerRows = '';
  data.seller_ranking.forEach((s, i) => {
    sellerRows += `<tr>
      <td style="text-align:center">${i + 1}</td>
      <td><a href="https://aucfan.com/seller/${encodeURIComponent(s.seller_id)}/" target="_blank" style="color:#2563eb">${escHtml(s.seller_id)}</a></td>
      <td style="text-align:center">${s.item_count}</td>
      <td style="text-align:center">${s.group_count}</td>
      <td style="text-align:center">${fmt(s.min_price)} 〜 ${fmt(s.max_price)}</td>
    </tr>`;
  });

  // ── 自演出品候補 ──
  let suspiciousRows = '';
  if (data.suspicious.length === 0) {
    suspiciousRows = '<tr><td colspan="4" style="text-align:center;color:#6b7280">該当なし</td></tr>';
  } else {
    data.suspicious.forEach(s => {
      suspiciousRows += `<tr>
        <td>${escHtml(s.title)}</td>
        <td style="text-align:center">${s.item_count}</td>
        <td>${s.dup_sellers.map(x => escHtml(x)).join(', ')}</td>
      </tr>`;
    });
  }

  // ── グループ分析（件数多い順） ──
  let groupRows = '';
  data.group_report.forEach(g => {
    const dupBadge = g.dup_sellers.length > 0
      ? `<span style="color:#dc2626;font-size:11px">⚠️自演疑い</span>` : '';
    const largeBadge = g.too_large
      ? `<span style="color:#d97706;font-size:11px">⚠️グループ大きすぎ(誤検知の可能性)</span>` : '';
    groupRows += `<tr style="${g.too_large ? 'opacity:0.5' : ''}">
      <td>${escHtml(g.title)} ${largeBadge}</td>
      <td style="text-align:center">${g.item_count}</td>
      <td style="text-align:center">${g.seller_count}</td>
      <td style="text-align:center">${fmt(g.min_price)} 〜 ${fmt(g.max_price)}</td>
      <td style="font-size:12px">${g.sellers.map(x => escHtml(x)).join(', ')} ${dupBadge}</td>
    </tr>`;
  });

  return `
    <div style="margin-bottom:16px;padding:12px;background:#f3f4f6;border-radius:8px">
      <strong>総商品数:</strong> ${data.total_items.toLocaleString()}件
      <strong>セラー数:</strong> ${data.total_sellers.toLocaleString()}名
      <strong>グループ数:</strong> ${data.total_groups.toLocaleString()}件
    </div>

    <h3 style="margin:16px 0 8px;font-size:15px">🏆 セラー出品数ランキング（上位50名）</h3>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#f9fafb;text-align:left">
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">#</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">セラーID</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">出品数</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">グループ数</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">価格帯</th>
        </tr></thead>
        <tbody>${sellerRows}</tbody>
      </table>
    </div>

    <h3 style="margin:24px 0 8px;font-size:15px">⚠️ 同一セラー複数出品（自演出品の可能性）</h3>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#fef2f2;text-align:left">
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">商品タイトル</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">件数</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">重複セラー</th>
        </tr></thead>
        <tbody>${suspiciousRows}</tbody>
      </table>
    </div>

    <h3 style="margin:24px 0 8px;font-size:15px">📦 グループ別分析（件数多い順）</h3>
    <div style="overflow-x:auto">
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:#f9fafb;text-align:left">
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">タイトル</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">件数</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">セラー数</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">価格帯</th>
          <th style="padding:6px 8px;border-bottom:1px solid #e5e7eb">セラー一覧</th>
        </tr></thead>
        <tbody>${groupRows}</tbody>
      </table>
    </div>
  `;
}

let toastTimer;
function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.style.background = type === 'error' ? '#dc2626' : '#111827';
  el.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('show'), 3000);
}
