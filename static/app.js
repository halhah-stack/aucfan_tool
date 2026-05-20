/* ─────────────────────────────────────────────
   AucFan リサーチツール フロントエンド
───────────────────────────────────────────── */

// ─── アプリ全体の状態管理 ───
// すべての UI 状態をここで一元管理する。
// React のような仮想 DOM は使わず、各関数が必要なタイミングで DOM を直接更新する。
const state = {
  // ── スクレイピング状態 ──
  isRunning: false,          // バックエンドのスクレイパースレッドが実行中かどうか（SSE で更新）

  // ── ページネーション ──
  currentPage: 1,            // 現在表示中のページ番号
  totalPages: 1,             // 総ページ数（API レスポンスから更新）
  totalGroups: 0,            // 総グループ数（API レスポンスから更新）

  // ── フィルター ──
  filterStatus: '',          // ステータスフィルター（'candidate'|'ok'|'ng'等、''=全て）
  filterKeyword: '',         // タイトル・キーワードの部分一致フィルター
  filterMinPrice: 0,         // 価格下限（円）
  filterMaxPrice: 99999,     // 価格上限（円）
  filterMinGroup: 1,         // 最小グループ件数フィルター

  // ── タイマー・接続 ──
  refreshInterval: null,     // 自動更新タイマー（スクレイピング中のみ動作）
  sseSource: null,           // SSE（EventSource）接続オブジェクト

  // ── モード ──
  isSellerAnalysis: false,   // セラー分析モード（STEP 2 / STEP 3 時は true）
                             // → true 時のみ価格ソートバーを表示
  sellerDetailMinGroup: 3,   // Gemini 判定対象の最小グループ件数（サーバーの SELLER_DETAIL_MIN_GROUP）
  activeStep: 1,             // 現在アクティブなステップ (1 / 2 / 3 / 'master')
  showNgList: false,         // NG一覧セクションの表示/非表示

  // ── クライアントサイドソート ──
  // API からのデータを再取得せずに並び替えるためにキャッシュする。
  // セラー分析モードは 300 件まで一括取得してここに保持する。
  sortCount: 'desc',         // 件数ソート: 'desc'=多い順 / 'asc'=少ない順 / ''=指定なし
  sortPrice: '',             // 価格ソート: 'desc'=高い順 / 'asc'=安い順 / ''=指定なし
                             // ※ STEP 2（セラー分析）のみ表示。件数同値時の第2キーとして機能。
  allGroups: [],             // ソート用グループキャッシュ（loadGroups で更新）
};

// ─── 初期化 ───
document.addEventListener('DOMContentLoaded', () => {
  startSSE();
  loadGroups();
  refreshCurrentSession(); // 表示中セッションバーを初期化

  // ── タブ復元（画面更新後も前回のステップを維持する） ──
  // localStorage に保存された最後のステップへ切り替える。
  // 保存値がなければ STEP 1 を表示。
  const savedStep = localStorage.getItem('activeStep');
  const restoredStep = savedStep === '2' ? 2
                     : savedStep === '3' ? 3
                     : savedStep === 'master' ? 'master'
                     : 1;
  switchStep(restoredStep);

  setInterval(() => {
    if (state.isRunning) loadGroups(); // スクレイピング中のみ自動更新
  }, 8000);
});

// ─────────────────────────────────────────────
// ステップ切り替え
// ─────────────────────────────────────────────
/**
 * 指定ステップのパネル・タブを切り替える。
 * 各ステップへの切り替え時に以下の副作用を伴う:
 *   step=1      : キーワードセッション一覧を再読み込み
 *   step=2      : セラー履歴・STEP 1セッションリスト・現在のスクレイピングステータスを再取得
 *   step=3      : マスター分析ステータス・セッション履歴・統計ミニ表示を再取得
 *   step='master': マスターセラーリスト管理画面を表示・再読み込み
 * @param {number|string} step - 切り替え先ステップ (1 / 2 / 3 / 'master')
 */
function switchStep(step) {
  state.activeStep = step;

  // 現在のステップを localStorage に保存（画面更新後も復元できるように）
  localStorage.setItem('activeStep', String(step));

  const p1  = document.getElementById('step1Panel');
  const p2  = document.getElementById('step2Panel');
  const p3  = document.getElementById('step3Panel');
  const pm  = document.getElementById('masterPanel');
  const t1  = document.getElementById('stepTab1');
  const t2  = document.getElementById('stepTab2');
  const t3  = document.getElementById('stepTab3');
  const tm  = document.getElementById('stepTabMaster');

  if (p1) p1.style.display = step === 1        ? '' : 'none';
  if (p2) p2.style.display = step === 2        ? '' : 'none';
  if (p3) p3.style.display = step === 3        ? '' : 'none';
  if (pm) pm.style.display = step === 'master' ? '' : 'none';

  if (t1) t1.classList.toggle('active', step === 1);
  if (t2) t2.classList.toggle('active', step === 2);
  if (t3) t3.classList.toggle('active', step === 3);
  if (tm) tm.classList.toggle('active', step === 'master');

  // ソートバーの価格グループをステップに応じて表示切替
  const _sortPriceGroup = document.getElementById('sortPriceGroup');
  if (_sortPriceGroup) _sortPriceGroup.style.display = state.isSellerAnalysis ? '' : 'none';

  if (step === 1) {
    loadKeywordSessions();
  }
  if (step === 2) {
    loadSellerHistory();
    loadStep2KeywordSessions();
    fetchSellerStatus(/* silent */ true);
  }
  if (step === 3) {
    fetchMasterStatus(/* silent */ true);
    loadStep3History();
    // STEP 3パネルのミニ統計を更新
    fetchJSON('/api/master_sellers/stats').then(d => {
      const el1 = document.getElementById('step3MasterTotal');
      const el2 = document.getElementById('step3MasterUnscraped');
      if (el1) el1.textContent = d.total ?? '—';
      if (el2) el2.textContent = d.unscraped ?? '—';
    }).catch(() => {});
  }
  if (step === 'master') {
    loadMasterSellers();
  }
}

// ─────────────────────────────────────────────
// セッション名パーサー（共通ユーティリティ）
// ─────────────────────────────────────────────

/**
 * セッション名を分解して表示用オブジェクトを返す。
 * 新命名規則 S1_YYYYMMDD_NN_keyword・旧命名規則 keyword_YYYYMMDD_HHMMSS の両方に対応。
 */
function parseSessionName(name) {
  if (!name) return { label: '—', dateStr: '', step: 1, num: 0 };

  // 新命名規則: S1_20260506_01_バフ / S2_20260506_01 / S3_20260506_01
  const mNew = name.match(/^S(\d)_(\d{4})(\d{2})(\d{2})_(\d+)(?:_(.+))?$/);
  if (mNew) {
    const [, s, y, mo, d, num, kw] = mNew;
    const stepNum = parseInt(s);
    const lbl = stepNum === 1 ? (kw || 'STEP 1')
              : stepNum === 2 ? 'セラー分析'
              : 'マスター分析';
    return { label: lbl, dateStr: `${y}/${mo}/${d} #${num}`, step: stepNum, num: parseInt(num) };
  }

  // 旧命名規則: keyword_YYYYMMDD_HHMMSS
  const m = name.match(/^(.+?)_(\d{8})_(\d{6})$/);
  if (!m) return { label: name, dateStr: '', step: 1, num: 0 };
  let [, kw, date, time] = m;
  const y = date.slice(0,4), mo = date.slice(4,6), d = date.slice(6,8);
  const h = time.slice(0,2), mi = time.slice(2,4);
  const stepMap = { seller_analysis: 2, master_analysis: 3 };
  const lblMap  = { seller_analysis: 'セラー分析', master_analysis: 'マスター分析' };
  return {
    label:   lblMap[kw] || kw,
    dateStr: `${y}/${mo}/${d} ${h}:${mi}`,
    step:    stepMap[kw] || 1,
    num:     0,
  };
}

/**
 * ステータスラベルを色付きスパンで返す
 */
function sessionStatusSpan(status) {
  const map = {
    done:    '<span class="meta-status-done">✅ 完了</span>',
    stopped: '<span class="meta-status-stopped">⏹ 停止</span>',
    error:   '<span class="meta-status-error">❌ エラー</span>',
  };
  return map[status] || `<span>${escHtml(status || '—')}</span>`;
}

// ─────────────────────────────────────────────
// STEP 1: キーワードセッション一覧
// ─────────────────────────────────────────────

async function loadKeywordSessions() {
  const el = document.getElementById('step1SessionsList');
  if (!el) return;
  el.innerHTML = '<span style="color:#9ca3af;font-size:13px">読み込み中...</span>';

  const data = await fetchJSON('/api/sessions?step=1');
  const sessions = data.sessions || [];

  if (sessions.length === 0) {
    el.innerHTML = '<span style="color:#9ca3af;font-size:13px">Google DriveにSTEP 1のセッションが見つかりません</span>';
    return;
  }

  el.innerHTML = sessions.map(s => {
    const dis = s.is_running ? 'disabled' : '';
    const disTitle = s.is_running ? 'スクレイピング中は選択できません' : '';
    return `
    <div class="session-row">
      <div class="session-row-info">
        <div class="session-row-keyword">${escHtml(s.label || s.keyword)}</div>
        <div class="session-row-meta">
          <span class="meta-count">${(s.total_items || 0).toLocaleString()}件</span>
          <span class="meta-date">${escHtml(s.date_str)}</span>
          ${sessionStatusSpan(s.status)}
          ${s.is_running ? '<span class="meta-running">🔄 実行中</span>' : ''}
        </div>
      </div>
      <div class="session-row-actions">
        <button class="btn btn-primary btn-sm session-load-btn"
                title="${disTitle || 'グリッドに表示'}"
                ${dis} onclick="loadSessionToGrid('${escHtml(s.name)}')">📂 表示</button>
        <button class="btn btn-secondary btn-sm"
                title="${disTitle || 'STEP 2にセット'}"
                ${dis} onclick="sellerIdsFromSession('${escHtml(s.name)}')">→ S2</button>
        <button class="btn-delete"
                title="このセッションを削除（復元不可）"
                onclick="deleteSession('${escHtml(s.name)}', 1)">🗑</button>
      </div>
    </div>`;
  }).join('');
}

// ─────────────────────────────────────────────
// STEP 2 右カラム: STEP 1セッション選択リスト
// ─────────────────────────────────────────────

async function loadStep2KeywordSessions() {
  const el = document.getElementById('step2KeywordSessionsList');
  if (!el) return;
  el.innerHTML = '<span style="color:#9ca3af;font-size:12px">読み込み中...</span>';

  const data = await fetchJSON('/api/sessions?step=1');
  const sessions = data.sessions || [];

  if (sessions.length === 0) {
    el.innerHTML = '<span style="color:#9ca3af;font-size:12px">Google DriveにSTEP 1のセッションが見つかりません</span>';
    return;
  }

  el.innerHTML = sessions.map(s => `
    <div class="session-row" style="margin-bottom:4px;padding:6px 8px">
      <div class="session-row-info">
        <div class="session-row-keyword" style="font-size:12px">${escHtml(s.label || s.keyword)}</div>
        <div class="session-row-meta">
          <span class="meta-count">${(s.total_items || 0).toLocaleString()}件</span>
          <span class="meta-date">${escHtml(s.date_str)}</span>
        </div>
      </div>
      <div class="session-row-actions">
        <button class="btn btn-primary btn-sm"
                style="font-size:11px;padding:4px 10px"
                onclick="sellerIdsFromSession('${escHtml(s.name)}')">このセッションを使用</button>
      </div>
    </div>`).join('');
}

// ─────────────────────────────────────────────
// 指定セッションからセラーIDを抽出してSTEP 2にセット
// ─────────────────────────────────────────────

async function sellerIdsFromSession(sessionName) {
  showToast(`⏳ ${sessionName} からセラーIDを取得中...`);

  const res = await fetchJSON(`/api/sessions/${encodeURIComponent(sessionName)}/seller_ids`, 'POST');
  if (res.error) {
    showToast('❌ ' + res.error, 'error');
    return;
  }

  const { label, dateStr } = parseSessionName(sessionName);
  setActiveSource('sourceBox2',
    `✅ 使用中: 「${escHtml(label)}」（${dateStr}）${res.count}件`);
  document.getElementById('sellerImportSummary').textContent =
    `${res.count} 件のユニークセラーIDを取得しました（seller_url: ${res.has_seller_url ? 'あり ✅' : 'なし ⚠ フォールバックURLを使用'}）`;

  renderSellerTable(res.sellers);
  document.getElementById('sellerImportResult').style.display = 'block';
  document.getElementById('sellerListMeta').textContent = `${res.count} 件`;

  // STEP 2 に切り替え
  switchStep(2);
  showToast(`✅ ${res.count} 件のセラーIDをセットしました`);
}

// ─────────────────────────────────────────────
// セッション削除
// ─────────────────────────────────────────────

async function deleteSession(sessionName, step) {
  const { label, dateStr } = parseSessionName(sessionName);
  const displayName = `${label}（${dateStr}）`;

  if (!confirm(`「${displayName}」を削除しますか？\n\n画像を含むフォルダが完全に削除されます。この操作は取り消せません。`)) {
    return;
  }

  const res = await fetchJSON(`/api/sessions/${encodeURIComponent(sessionName)}`, 'DELETE');
  if (!res.success) {
    showToast('❌ 削除失敗: ' + (res.message || '不明なエラー'), 'error');
    return;
  }

  showToast(`🗑 「${displayName}」を削除しました`);

  // ステップに応じてリストを再読み込み（数値・旧文字列どちらにも対応）
  const stepNum = typeof step === 'number' ? step
                : step === 'keyword' ? 1 : step === 'seller' ? 2 : 3;
  if (stepNum === 1) {
    loadKeywordSessions();
    loadStep2KeywordSessions();
  } else if (stepNum === 2) {
    loadSellerHistory();
  } else {
    loadStep3History();
  }
  loadGroups();
  refreshCurrentSession();
}

// ─────────────────────────────────────────────
// SSE（リアルタイム進捗）
// ─────────────────────────────────────────────
/**
 * サーバーとの SSE（Server-Sent Events）接続を開始する。
 * /api/stream に接続して進捗データをリアルタイムで受信し、
 * パースした JSON を updateProgressUI() に渡してUIを更新する。
 * 接続エラー（onerror）時は5秒後に自動再接続する。
 * 既存の接続がある場合は先に close() してから新規接続する（二重接続防止）。
 */
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

/**
 * SSEから受信した進捗データをUIに反映する。
 * - ヘッダーステータス文字列・進捗バー・進捗カウンター・統計バッジを更新する。
 * - status 値に応じて進捗バーの表示内容を切り替える:
 *     'scraping_list'   : 一覧ページ取得の進捗（pages_done / total_pages）
 *     'scraping_detail' : 詳細ページ取得の進捗（detail_pages_done / detail_pages_total）
 *     'grouping'        : グループ化中（バー固定70%）
 *     'done'            : 完了（バー100%、完了バナーを表示）
 * - is_running の変化でGeminiポーリングの開始・停止を制御する。
 *
 * @param {object}  data                    - SSEペイロード（/api/stream からのJSONオブジェクト）
 * @param {object}  data.progress           - スクレイピング進捗オブジェクト
 * @param {string}  data.progress.status    - 'idle'|'scraping_list'|'scraping_detail'|
 *                                            'grouping'|'vision_check'|'done'|'stopped'|'error'
 * @param {string}  data.progress.keyword   - スクレイピング対象キーワード
 * @param {number}  data.progress.pages_done          - 取得済み一覧ページ数
 * @param {number}  data.progress.total_items         - 取得済み商品総数
 * @param {number}  data.progress.detail_pages_done   - 詳細取得済み件数
 * @param {number}  data.progress.detail_pages_total  - 詳細取得対象の総件数
 * @param {number}  data.progress.processed_items     - 処理（判定）済みアイテム数
 * @param {object}  data.stats              - 集計統計オブジェクト
 * @param {number}  data.stats.total        - 全アイテム数
 * @param {object}  data.stats.by_status    - ステータス別件数 {candidate, ok, ng, review, waiting}
 * @param {boolean} data.is_running         - スクレイパースレッドが実行中かどうか
 * @param {boolean} data.is_seller_analysis - セラー分析モード中かどうか
 */
function updateProgressUI(data) {
  const { progress, stats, is_running } = data;
  const wasRunning = state.isRunning;   // 完了遷移を検出するため先に保存
  state.isRunning = is_running;

  // Gemini レート制限ポーリング: スクレイピング中は開始、停止後は終了してから最終確認
  if (is_running) {
    startGeminiStatusPolling();
  } else {
    stopGeminiStatusPolling();
    checkGeminiStatus();   // 停止直後に1回チェック
  }

  // セラー分析モード切り替え
  const prevSellerMode = state.isSellerAnalysis;
  state.isSellerAnalysis = data.is_seller_analysis || false;
  const saFilter = document.getElementById('sellerAnalysisFilter');
  if (saFilter) saFilter.style.display = state.isSellerAnalysis ? '' : 'none';
  // モードが切り替わったらグループを再描画（バッジ表示を更新）
  if (prevSellerMode !== state.isSellerAnalysis) loadGroups();

  // ヘッダーステータス
  const statusLabels = {
    idle: '待機中', scraping_list: '一覧取得中', scraping_detail: '詳細取得中',
    grouping: 'グループ化中', vision_check: '🤖 Vision判定中',
    done: '完了', stopped: '停止済み', error: 'エラー',
    candidate: '仕入れ候補', next_candidate: '次期候補',
    login_required: '⚠️ ログイン待ち',
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

  // ── 進捗カウンター (#progressCounter) ──
  const progCounter = document.getElementById('progressCounter');
  const step1Banner = document.getElementById('step1CompletionBanner');
  const step1Count  = document.getElementById('step1CompletionCount');
  if (is_running) {
    // 新規スクレイピング開始時は完了バナーを隠す
    if (step1Banner) step1Banner.style.display = 'none';

    if (progress.status === 'scraping_list') {
      const pi = progress.processed_items || progress.total_items || 0;
      if (progCounter) {
        progCounter.style.display = '';
        progCounter.textContent = `処理済み: ${pi.toLocaleString()}件`;
      }
    } else if (progress.status === 'scraping_detail') {
      const pi = progress.processed_items || progress.detail_pages_done || 0;
      const ti = progress.detail_pages_total || 0;
      if (progCounter) {
        progCounter.style.display = '';
        progCounter.textContent = ti > 0
          ? `${pi.toLocaleString()}件 / ${ti.toLocaleString()}件処理済み`
          : `処理済み: ${pi.toLocaleString()}件`;
      }
    } else {
      if (progCounter) progCounter.style.display = 'none';
    }
  } else {
    if (progCounter) progCounter.style.display = 'none';
    // running → 停止 の瞬間に完了バナーを表示
    if (wasRunning && (progress.status === 'done' || progress.status === 'stopped')) {
      if (step1Banner && step1Count) {
        step1Count.textContent = `${(progress.total_items || 0).toLocaleString()}件処理`;
        step1Banner.style.display = 'flex';
      }
    }
  }

  // ボタン状態
  const btnStart = document.getElementById('btnStart');
  const btnStop = document.getElementById('btnStop');
  if (btnStart) btnStart.disabled = is_running;
  if (btnStop) btnStop.disabled = !is_running;

  // ── スクレイピングバナー更新（キーワードリサーチ用） ──
  // セラー分析中は fetchSellerStatus 側でバナーを管理するためスキップ
  if (!state.isSellerAnalysis) {
    // ログイン待ち（STEP1）
    if (progress.status === 'login_required') {
      updateBanner({
        isActive: true, icon: '⚠️', type: 'login',
        main: 'AucFanのログインが切れました',
        sub:  'Chromeで aucfan.com にログイン後、自動再開（30秒）またはボタンで即再開。',
        showLoginBtn: true,
      });
      // ヘッダー更新（SSEのstatusLabels経由より確実）
      const statusEl = document.getElementById('headerStatus');
      if (statusEl) {
        statusEl.textContent = '⚠️ ログイン待ち';
        statusEl.style.background = 'rgba(255,255,255,.35)';
      }
      return;
    }
    if (is_running) {
      const phaseText = {
        scraping_list:   '一覧取得中',
        scraping_detail: '詳細取得中',
        grouping:        'グループ化中',
        vision_check:    '🤖 Vision判定中',
      }[progress.status] || progress.status;

      const pageInfo = progress.status === 'scraping_list'
        ? `ページ ${progress.pages_done || 0} / ${config_MAX_PAGES}`
        : progress.status === 'scraping_detail'
          ? `詳細 ${progress.detail_pages_done || 0} / ${progress.detail_pages_total || '?'} 件`
          : '';

      updateBanner({
        isActive: true,
        main: `${phaseText}...`,
        sub:  `商品 ${progress.total_items || 0}件取得中${pageInfo ? '  |  ' + pageInfo : ''}`,
      });
    } else if (progress.status === 'done') {
      updateBanner({
        isActive: true, icon: '✅', type: 'done',
        main: '完了',
        sub:  `商品 ${progress.total_items || 0}件取得`,
        autohide: 10000,
      });
    } else if (progress.status === 'stopped') {
      updateBanner({
        isActive: true, icon: '⏹', type: 'stopped',
        main: '停止',
        sub:  `商品 ${progress.total_items || 0}件取得`,
        autohide: 8000,
      });
    } else if (progress.status === 'error') {
      updateBanner({
        isActive: true, icon: '❌', type: 'error',
        main: 'エラーが発生しました',
        sub:  'ターミナルのログを確認してください',
        autohide: 15000,
      });
    } else {
      updateBanner({ isActive: false });
    }
  }

  // 統計（仕入れ候補・OK・NG・要確認はグループ単位、取得件数はアイテム総数）
  if (stats) {
    const byStatus = stats.by_status || {};
    setText('statTotal', stats.total || 0);
    setText('statCandidate', byStatus.candidate || 0);          // グループ数
    setText('statNextCandidate', byStatus.next_candidate || 0); // グループ数
    setText('statReview', byStatus.review || 0);                // グループ数
    setText('statOk', byStatus.ok || 0);                       // グループ数
    setText('statNg', byStatus.ng || 0);                       // グループ数
  }
}

// ─────────────────────────────────────────────
// スクレイピング制御
// ─────────────────────────────────────────────
const config_MAX_PAGES = 500; // サーバー設定と合わせる

// ─────────────────────────────────────────────
// Chromeタブ確認（iPhone / iPad用）
// ─────────────────────────────────────────────
let _selectedTabUrl = '';

async function loadChromeTabs() {
  const hint = document.getElementById('tabsHint');
  const list = document.getElementById('chromeTabs');
  hint.textContent = '取得中...';
  list.style.display = 'none';

  const data = await fetchJSON('/api/tabs');

  if (data.error) {
    hint.textContent = '⚠️ ' + data.error;
    return;
  }

  const tabs = data.tabs || [];
  if (tabs.length === 0) {
    hint.textContent = 'AucFanのタブが見つかりません';
    return;
  }

  hint.textContent = `${tabs.length}件のAucFanタブが見つかりました`;
  list.style.display = 'flex';
  list.innerHTML = tabs.map(t => `
    <div class="chrome-tab-item" id="tab-${btoa(t.url).substring(0,10)}"
         onclick="selectTab('${escHtml(t.url)}', this)">
      <div class="chrome-tab-info">
        <div class="chrome-tab-title">${escHtml(t.title || t.url)}</div>
        <div class="chrome-tab-url">${escHtml(t.url)}</div>
      </div>
      <button class="btn btn-primary btn-sm">選択</button>
    </div>
  `).join('');
}

function selectTab(url, el) {
  _selectedTabUrl = url;
  document.querySelectorAll('.chrome-tab-item').forEach(e => e.classList.remove('selected'));
  el.classList.add('selected');
  // URL入力欄はクリア（タブ選択優先）
  const urlInput = document.getElementById('inputStartUrl');
  if (urlInput) urlInput.value = '';
  showToast('タブを選択しました。キーワードを確認してスクレイピング開始してください。');
}

async function startScraping() {
  const keyword  = document.getElementById('inputKeyword').value.trim() || 'unknown';
  // ① タブ選択 ② URL貼り付け の優先順位
  const pastedUrl = (document.getElementById('inputStartUrl')?.value || '').trim();
  const startUrl = _selectedTabUrl || pastedUrl;

  if (startUrl && !startUrl.startsWith('http')) {
    showToast('❌ URLが正しくありません（https://... から始めてください）', 'error');
    return;
  }

  const payload = { keyword, resume: false };
  if (startUrl) payload.start_url = startUrl;

  const res = await fetchJSON('/api/start', 'POST', payload);
  if (res.success) {
    const msg = startUrl
      ? `🌐 URLに遷移してスクレイピング開始: ${keyword}`
      : `▶ スクレイピング開始: ${keyword}`;
    showToast(msg);
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
/**
 * サーバーから商品グループ一覧を取得してグリッドに描画する。
 * state のフィルター条件（filterStatus / filterKeyword / filterMinPrice 等）を
 * クエリパラメータに変換して /api/items に GET リクエストを送る。
 * セラー分析モード時は per_page=300 で全件取得し、クライアント側でソートする。
 * ページ切り替え時はグリッド先頭へスクロールする。
 * @param {number} [page] - 表示するページ番号（省略時は state.currentPage を維持）
 */
async function loadGroups(page) {
  const isPageChange = !!page;   // ユーザーがページボタンを押したか
  if (page) state.currentPage = page;

  // セラー分析モードは全件まとめて取得してクライアントソートしやすくする
  const perPage = state.isSellerAnalysis ? 300 : 50;

  const params = new URLSearchParams({
    status: state.filterStatus,
    keyword: state.filterKeyword,
    min_price: state.filterMinPrice,
    max_price: state.filterMaxPrice,
    min_group: state.filterMinGroup,
    page: state.currentPage,
    per_page: perPage,
  });

  const data = await fetchJSON(`/api/items?${params}`);
  if (!data || !data.groups) return;

  state.totalPages = data.total_pages || 1;
  state.totalGroups = data.total_groups || 0;

  // セラー分析フラグとGemini対象閾値をAPIから取得
  if (data.is_seller_analysis !== undefined) {
    const wasSellerAnalysis = state.isSellerAnalysis;
    state.isSellerAnalysis = data.is_seller_analysis;
    const saFilter = document.getElementById('sellerAnalysisFilter');
    if (saFilter) saFilter.style.display = state.isSellerAnalysis ? '' : 'none';
    // ソートバーの表示切替（Step1でも件数ソートを使えるよう常に表示）
    const sortBar = document.getElementById('sortBar');
    if (sortBar) sortBar.style.display = '';
    // 価格ソートはセラー分析モード時のみ表示
    const priceGroup = document.getElementById('sortPriceGroup');
    if (priceGroup) priceGroup.style.display = state.isSellerAnalysis ? '' : 'none';
    // セラー分析モードを初めて検出したときのみ STEP 2 タブへ自動切り替え
    if (!wasSellerAnalysis && state.isSellerAnalysis) {
      switchStep(2);
      loadGroups(1);
      return;
    }
  }
  if (data.seller_detail_min_group !== undefined) {
    state.sellerDetailMinGroup = data.seller_detail_min_group;
  }

  // クライアントサイドソート用にグループをキャッシュ
  state.allGroups = data.groups || [];

  // ソート適用してレンダリング
  renderGroups(sortGroups(state.allGroups));
  renderPagination();
  setText('groupsCount', `グループ: ${state.totalGroups}件`);
  updateSortHint();

  // ページ切り替え時はグリッド先頭へスクロール
  if (isPageChange) {
    const target = document.getElementById('sortBar') &&
                   document.getElementById('sortBar').offsetParent
      ? document.getElementById('sortBar')
      : document.getElementById('groupsGrid');
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
}

function renderGroups(groups) {
  const grid = document.getElementById('groupsGrid');
  const empty = document.getElementById('emptyState');

  // NG グループを分離（メイングリッドには表示しない）
  const ngGroups = (groups || []).filter(g => g.status === 'ng');
  const mainGroups = (groups || []).filter(g => g.status !== 'ng');

  if (mainGroups.length === 0) {
    grid.innerHTML = '';
    if (empty) {
      empty.style.display = '';
      grid.appendChild(empty);
    }
  } else {
    if (empty) empty.style.display = 'none';
    grid.innerHTML = mainGroups.map(g => renderGroupCard(g)).join('');
  }

  // NG セクションを更新
  renderNgList(ngGroups);
}

// ─────────────────────────────────────────────
// クライアントサイド ソート
// ─────────────────────────────────────────────

/**
 * グループの「最安合計価格（送料込み）」を返すヘルパー。
 * カード上の価格表示には使わず、将来的な合計値ソート用の予備関数。
 */
function getGroupMinTotal(group) {
  if (!group.items || group.items.length === 0) return group.min_price || 0;
  return Math.min(
    ...group.items.map(i => i.total || ((i.price || 0) + (i.shipping || 0)))
  );
}

/**
 * グループの代表価格を返す（ソートキーとして使用）。
 *
 * 価格の取得優先順位:
 *   1. items[0].price  — カード表示と同じ値でソートするため優先
 *   2. group.min_price — Python 側が全アイテムの非ゼロ価格から計算した最小値
 *      （items[0].price が 0 または未設定の場合のフォールバック）
 *
 * Note: price=0 の商品が先頭に来るケースを防ぐため、0 の場合は min_price を使う。
 */
function getGroupRepPrice(group) {
  const itemPrice = group.items && group.items[0] ? Number(group.items[0].price) : 0;
  const minPrice  = Number(group.min_price) || 0;
  const p = itemPrice > 0 ? itemPrice : minPrice;
  return isNaN(p) ? 0 : p;
}

/**
 * state.sortCount / state.sortPrice の設定に従いグループ配列をソートして返す。
 *
 * ソートキーの優先順位:
 *   第1キー: 件数（group.count）— sortCount が '' の場合はスキップ
 *   第2キー: 価格（getGroupRepPrice）— sortPrice が '' の場合はスキップ
 *
 * 使用上の注意:
 *   全グループの件数がすべて異なる場合、第2キーの価格ソートは実質無効になる。
 *   価格だけで並び替えたい場合は sortCount を '' (指定なし) にすること。
 *
 * デバッグ用コンソールログ:
 *   ソート前に件数上位5件・価格上位5件をコンソールに出力する（開発用）。
 */
function sortGroups(groups) {
  if (!groups || groups.length === 0) return groups || [];
  if (groups.length > 0) {
    const counts = [...new Set(groups.map(g => g.count || 0))].sort((a,b) => b-a).slice(0,5);
    const prices = groups.map(g => getGroupRepPrice(g)).filter(p => p > 0).sort((a,b) => b-a).slice(0,5);
    console.log(`[sort] ${groups.length}グループ, sortCount="${state.sortCount}", sortPrice="${state.sortPrice}"`);
    console.log(`[sort] count上位: ${counts.join(',')}  price上位: ${prices.join(',')}`);
  }
  return [...groups].sort((a, b) => {
    // 第1キー: 件数ソート（sortCount='' の「指定なし」のときはこのブロックをスキップ）
    if (state.sortCount) {
      const countDir = state.sortCount === 'asc' ? 1 : -1;
      const cd = ((a.count || 0) - (b.count || 0)) * countDir;
      if (cd !== 0) return cd;
      // 件数が同値の場合は第2キー（価格）へ進む
    }
    // 第2キー: 価格ソート（件数同値のとき、または件数ソートが「指定なし」のとき）
    if (state.sortPrice) {
      const priceDir = state.sortPrice === 'asc' ? 1 : -1;
      return (getGroupRepPrice(a) - getGroupRepPrice(b)) * priceDir;
    }
    return 0; // ソート指定なし: 取得順を維持
  });
}

/** ソート選択変更時：キャッシュを再ソートして再描画（API再取得なし） */
function applySort() {
  const selCount = document.getElementById('sortCount');
  const selPrice = document.getElementById('sortPrice');
  if (selCount) state.sortCount = selCount.value;
  if (selPrice) state.sortPrice = selPrice.value;
  if (state.allGroups.length > 0) {
    renderGroups(sortGroups(state.allGroups));
  }
  updateSortHint();
}

/** ソートバーのヒント文字列を更新 */
function updateSortHint() {
  const hint = document.getElementById('sortHint');
  if (!hint) return;
  const countLabel = state.sortCount === 'desc' ? '件数 多い順'
    : state.sortCount === 'asc' ? '件数 少ない順' : '';
  const priceLabel = state.sortPrice === 'asc' ? '価格 安い順'
    : state.sortPrice === 'desc' ? '価格 高い順' : '';
  const parts = [countLabel, priceLabel].filter(Boolean);
  hint.textContent = parts.length ? parts.join(' → ') : '並び替えなし';
}

function renderNgList(ngGroups) {
  const btn = document.getElementById('btnNgToggle');
  const section = document.getElementById('ngSection');
  const ngCount = document.getElementById('ngCount');
  const ngGrid = document.getElementById('ngGrid');
  const ngSub = document.getElementById('ngSectionSub');

  const totalNgItems = ngGroups.reduce((sum, g) => sum + (g.count || 1), 0);

  if (!ngGroups || ngGroups.length === 0) {
    if (btn) btn.style.display = 'none';
    if (section && !state.showNgList) section.style.display = 'none';
    return;
  }

  // トグルボタン表示
  if (btn) {
    btn.style.display = '';
    if (ngCount) ngCount.textContent = totalNgItems;
    btn.textContent = state.showNgList
      ? `❌ NG一覧を隠す`
      : `❌ NG一覧を表示 (${totalNgItems}件)`;
  }
  if (ngSub) {
    ngSub.textContent = `${totalNgItems}件 / ${ngGroups.length}グループ`;
  }

  // NG カード描画
  if (ngGrid) {
    ngGrid.innerHTML = ngGroups.map(g => {
      const item = g.items[0];
      const thumb = item.thumbnail_local
        ? `/images/${getFilename(item.thumbnail_local)}` : '';
      const title = item.title_full || item.title_short || '（タイトル不明）';
      const reason = item.exclude_reason || item.gemini_reason || '';
      const src = item.gemini_source || '';
      const badge = src === 'vision'
        ? '<span class="ng-badge ng-badge-vision">🤖 Vision NG</span>'
        : src === 'text'
          ? '<span class="ng-badge ng-badge-text">📝 テキスト NG</span>'
          : '<span class="ng-badge ng-badge-manual">手動 NG</span>';
      const thumbHtml = thumb
        ? `<img class="ng-thumb" src="${thumb}" alt="" loading="lazy"
               onerror="this.outerHTML='<div class=ng-thumb-placeholder>📦</div>'">`
        : '<div class="ng-thumb-placeholder">📦</div>';
      const countBadge = g.count > 1
        ? `<span class="ng-count-badge">${g.count}件</span>` : '';

      return `
        <div class="ng-item">
          ${thumbHtml}
          <div class="ng-item-info">
            <div class="ng-item-title">${escHtml(title)}${countBadge}</div>
            ${reason ? `<div class="ng-item-reason">${escHtml(reason)}</div>` : ''}
            <div class="ng-item-footer">${badge}
              <button class="btn btn-sm btn-secondary ng-restore-btn"
                      onclick="updateGroupStatus('${g.group_id}', 'waiting')">↩ 解除</button>
            </div>
          </div>
        </div>`;
    }).join('');
  }
}

function toggleNgList() {
  state.showNgList = !state.showNgList;
  const section = document.getElementById('ngSection');
  const btn = document.getElementById('btnNgToggle');
  const ngCount = document.getElementById('ngCount');
  if (section) section.style.display = state.showNgList ? '' : 'none';
  if (btn) {
    btn.textContent = state.showNgList
      ? `❌ NG一覧を隠す`
      : `❌ NG一覧を表示 (${ngCount ? ngCount.textContent : '0'}件)`;
  }
}

function renderGroupCard(group) {
  const statusClass = group.status || 'waiting';
  const statusLabel = {
    candidate: '仕入れ候補', next_candidate: '次期候補',
    waiting: '確認待ち', review: '要確認', ok: '✅ OK', ng: '❌ NG'
  }[statusClass] || statusClass;

  // セラー分析モード：グループサイズに応じたバッジを生成
  let sellerGroupBadge = '';
  if (state.isSellerAnalysis) {
    const gs = group.count;
    const minG = state.sellerDetailMinGroup;
    if (gs >= minG) {
      sellerGroupBadge = `<span class="sa-group-badge sa-badge-ai">🤖 AI判定対象</span>`;
    } else if (gs === 2) {
      sellerGroupBadge = `<span class="sa-group-badge sa-badge-watch">👀 2件一致</span>`;
    } else {
      sellerGroupBadge = `<span class="sa-group-badge sa-badge-ref">参考</span>`;
    }
  }

  // 【現在】サムネイルがある件数だけ表示（最大20枚）し、件数バッジと一致させる（2025-05-03 変更）
  // 【元に戻す場合】以下の4行をこのブロックと差し替える:
  //   const countLabel = group.count > 1 ? `同一商品 <span class="group-badge">${group.count}件</span>` : '単品';
  //   const thumbs = group.items.slice(0, 5).map(item => {
  //     const thumb = item.thumbnail_local ? `/images/${getFilename(item.thumbnail_local)}` : '';
  //     return thumb ? `<img class="card-thumb" ...>` : `<div class="card-thumb-placeholder">📦</div>`;
  //   }).join('');
  const thumbItems = group.items.filter(item => item.thumbnail_local).slice(0, 20);
  // バッジはソートと同じ group.count（全アイテム数）を使う
  const realCount = group.count || group.items.length;
  const countLabel = realCount > 1
    ? `同一商品 <span class="group-badge">${realCount}件</span>`
    : '単品';

  const thumbs = thumbItems.map(item => {
    const thumb = `/images/${getFilename(item.thumbnail_local)}`;
    return `<img class="card-thumb" src="${thumb}" alt="" loading="lazy"
                 onerror="this.outerHTML='<div class=card-thumb-placeholder>📦</div>'"
                 onclick="openItemDetail('${item.item_id}')">`;
  }).join('') || '<div class="card-thumb-placeholder">📦</div>';

  // 価格表示
  const firstItem = group.items[0];
  const price = firstItem.price || 0;
  const shipping = firstItem.shipping || 0;
  const total = firstItem.total || (price + shipping);

  // セラーID（全員表示、5件超は "+N" で省略）
  const allSellers = (group.seller_ids || []).filter(Boolean);
  const maxShow = 5;
  const shownSellers = allSellers.slice(0, maxShow);
  const extraCount = allSellers.length - shownSellers.length;
  const sellerBadges = shownSellers
    .map(s => `<span class="seller-badge">${escHtml(s)}</span>`).join('');
  const sellerExtra = extraCount > 0
    ? `<span class="seller-more">+${extraCount}</span>` : '';
  const sellerCountLabel = allSellers.length > 1
    ? `<span class="seller-count-label">${allSellers.length}名</span>` : '';
  const multiSellerClass = allSellers.length > 1 ? ' multi-seller' : '';

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
      <span style="font-size:10px;opacity:.6">件数:${group.count} ¥${getGroupRepPrice(group).toLocaleString()}</span>
    </div>
    <div class="card-images-wrap">
      <div class="card-images">${thumbs}</div>
    </div>
    <div class="card-body">
      <div class="card-title" onclick="openItemDetail('${firstItemId}')"
           title="${escHtml(group.title)}">${escHtml(group.title || '（タイトル取得中）')}</div>
      ${sellerGroupBadge}
      <div class="card-price-row">
        <div>
          <div class="card-price-label">${shipping > 0 ? '合計' : '価格'}</div>
          <div class="card-price">¥${(shipping > 0 ? total : price).toLocaleString()}</div>
        </div>
        ${shipping > 0 ? `
        <div class="card-price-sub">
          <div class="card-price-label">価格</div>
          <div class="price-val">¥${price.toLocaleString()}</div>
        </div>
        <div class="card-price-sub">
          <div class="card-price-label">送料</div>
          <div class="price-val">¥${shipping.toLocaleString()}</div>
        </div>` : ''}
      </div>
      <div class="card-sellers${multiSellerClass}">
        出品者${sellerCountLabel}: ${sellerBadges || '—'}${sellerExtra}
      </div>
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
      <button class="btn btn-danger btn-sm" onclick="showNgReasonModal('${groupId}')">
        ❌ NG
      </button>
    </div>
  </div>`;
}

// ─────────────────────────────────────────────
// NG 理由入力モーダル
// ─────────────────────────────────────────────
function showNgReasonModal(groupId) {
  // 既存モーダルを削除
  const existing = document.getElementById('ngReasonModal');
  if (existing) existing.remove();

  const modal = document.createElement('div');
  modal.id = 'ngReasonModal';
  modal.style.cssText = `
    position:fixed; inset:0; background:rgba(0,0,0,.45);
    display:flex; align-items:center; justify-content:center; z-index:9999;`;
  modal.innerHTML = `
    <div style="background:#fff; border-radius:10px; padding:24px; width:360px;
                box-shadow:0 8px 32px rgba(0,0,0,.2);">
      <p style="margin:0 0 12px; font-weight:600; font-size:15px;">❌ NG理由を入力（任意）</p>
      <input id="ngReasonInput" type="text" placeholder="例: KOVAXはブランド名なので除外"
        style="width:100%; box-sizing:border-box; padding:8px 10px; border:1px solid #ccc;
               border-radius:6px; font-size:14px; margin-bottom:8px;"
        onkeydown="if(event.key==='Enter') submitNgReason('${groupId}');
                   if(event.key==='Escape') closeNgModal();" />
      <p id="ngReasonHint" style="font-size:12px; color:#888; margin:0 0 14px; min-height:16px;"></p>
      <div style="display:flex; gap:8px; justify-content:flex-end;">
        <button onclick="closeNgModal()"
          style="padding:7px 16px; border:1px solid #ccc; border-radius:6px;
                 background:#fff; cursor:pointer;">キャンセル</button>
        <button onclick="submitNgReason('${groupId}', true)"
          style="padding:7px 16px; border:none; border-radius:6px;
                 background:#6c757d; color:#fff; cursor:pointer;">理由なしでNG</button>
        <button onclick="submitNgReason('${groupId}')"
          style="padding:7px 16px; border:none; border-radius:6px;
                 background:#dc3545; color:#fff; cursor:pointer; font-weight:600;">❌ NGにする</button>
      </div>
    </div>`;
  document.body.appendChild(modal);
  const input = document.getElementById('ngReasonInput');
  input.focus();

  // 入力内容に応じてヒントを表示
  input.addEventListener('input', () => {
    const hint = document.getElementById('ngReasonHint');
    const val = input.value;
    if (/ブランド|メーカー|brand|maker/i.test(val)) {
      hint.style.color = '#e67e00';
      hint.textContent = '💡 ブランド・メーカー除外を検出。NGにすると除外キーワード追加を提案します。';
    } else {
      hint.style.color = '#888';
      hint.textContent = '';
    }
  });

  // モーダル外クリックで閉じる
  modal.addEventListener('click', e => { if (e.target === modal) closeNgModal(); });
}

function closeNgModal() {
  const m = document.getElementById('ngReasonModal');
  if (m) m.remove();
}

async function submitNgReason(groupId, skipReason = false) {
  const input = document.getElementById('ngReasonInput');
  const reason = skipReason ? '' : (input ? input.value.trim() : '');
  closeNgModal();
  await updateGroupStatus(groupId, 'ng', reason);

  // ブランド・メーカーキーワードを含む場合は追加提案を表示
  if (reason && /ブランド|メーカー|brand|maker/i.test(reason)) {
    // 理由から最初の単語（商品名）を抽出して提案
    const word = reason.split(/[はがのをにで\s]/)[0];
    setTimeout(() => {
      showExcludeKeywordSuggestion(word, reason);
    }, 800);
  }
}

function showExcludeKeywordSuggestion(word, fullReason) {
  const toast = document.createElement('div');
  toast.style.cssText = `
    position:fixed; bottom:80px; right:20px; background:#fff3cd;
    border:1px solid #e67e00; border-radius:8px; padding:14px 18px;
    max-width:340px; z-index:9998; box-shadow:0 4px 12px rgba(0,0,0,.15);
    font-size:13px; line-height:1.5;`;
  toast.innerHTML = `
    <p style="margin:0 0 6px; font-weight:600; color:#856404;">
      💡 除外キーワードへの追加を提案
    </p>
    <p style="margin:0 0 10px; color:#555;">
      「<b>${escHtml(word)}</b>」を .env の
      <code>EXCLUDE_MAKER_KEYWORDS</code> に追加すると<br>
      次回から自動除外されます。
    </p>
    <code style="display:block; background:#f8f9fa; padding:6px 8px;
                 border-radius:4px; font-size:12px; margin-bottom:10px; word-break:break-all;">
      EXCLUDE_MAKER_KEYWORDS=${escHtml(word)}
    </code>
    <button onclick="this.closest('div').remove()"
      style="padding:4px 12px; border:1px solid #ccc; border-radius:4px;
             background:#fff; cursor:pointer; font-size:12px;">閉じる</button>`;
  document.body.appendChild(toast);
  setTimeout(() => { if (toast.parentNode) toast.remove(); }, 15000);
}

// ─────────────────────────────────────────────
// ステータス更新
// ─────────────────────────────────────────────
async function updateGroupStatus(groupId, status, ngReason = '') {
  const body = { status };
  if (ngReason) body.ng_reason = ngReason;
  const res = await fetchJSON(`/api/group/${groupId}/status`, 'POST', body);
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
// HTML エクスポート（Mac用・ブラウザで開く用）
// ─────────────────────────────────────────────
async function exportHtml() {
  const btn = document.getElementById('btnExportHtml');
  const origLabel = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 書き出し中...'; }
  showToast('💻 HTMLを生成中...');

  try {
    const res = await fetch('/api/export/html');
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast('❌ ' + (err.error || '書き出し失敗'), 'error');
      return;
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    let filename = 'aucfan_Mac用.html';
    const match = disposition.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
    if (match) filename = decodeURIComponent(match[1].replace(/"/g, '').trim());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('✅ Mac用HTMLを保存しました（' + filename + '）');
  } catch (e) {
    showToast('❌ 書き出しエラー: ' + e, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origLabel || '💻 HTMLで保存（Mac用）'; }
  }
}

// ─────────────────────────────────────────────
// HTML エクスポート（iPhone/iPad オフライン用）
// ─────────────────────────────────────────────
/**
 * iPhone / iPad 向けオフライン閲覧用 HTML を Google Drive に保存する。
 * Mac サーバー側で HTML を生成して Google Drive フォルダに書き込む。
 * iPhone / Mac どちらから押しても Google Drive（Mac上）に保存される。
 * 生成中はボタンを無効化してスピナーラベルを表示する。
 *
 * @param {boolean} [onlyActive=false] - true のとき候補・OK・要確認のみ出力して軽量化する
 */
// ─────────────────────────────────────────────
// PDF エクスポート（iPhone用・仕入れ候補・次期候補）
// ─────────────────────────────────────────────
async function exportPdf() {
  const btn = document.getElementById('btnExportPdf');
  const origLabel = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = '⏳ PDF生成中...'; }
  showToast('📄 PDF生成中... 画像処理に少し時間がかかります');

  try {
    const res = await fetch('/api/export/pdf');
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast('❌ ' + (err.error || 'PDF生成失敗'), 'error');
      return;
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    let filename = 'aucfan_仕入れ候補.pdf';
    const match = disposition.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
    if (match) filename = decodeURIComponent(match[1].replace(/"/g, '').trim());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('✅ PDF保存完了（' + filename + '）');
  } catch (e) {
    showToast('❌ PDF書き出しエラー: ' + e, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = origLabel || '📄 PDF保存（iPhone用）'; }
  }
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
    document.getElementById('sessionsBody').innerHTML = '<p style="text-align:center;color:#6b7280;padding:30px">Google Driveにセッションが見つかりません</p>';
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

  const btnHTML = pages.map(p => {
    if (p === '...') return `<span style="padding:5px 4px;color:#9ca3af">…</span>`;
    const active = p === cur ? 'active' : '';
    return `<button class="page-btn ${active}" onclick="loadGroups(${p})">${p}</button>`;
  }).join('');

  const jumpHTML = `
    <span class="page-jump">
      <span class="page-jump-label">ページ指定:</span>
      <input class="page-jump-input" type="number" min="1" max="${total}"
             value="${cur}" id="pageJumpInput"
             onkeydown="if(event.key==='Enter') jumpToPage(this.value)">
      <span class="page-jump-total">/ ${total}</span>
      <button class="page-jump-btn" onclick="jumpToPage(document.getElementById('pageJumpInput').value)">移動</button>
    </span>`;

  return btnHTML + jumpHTML;
}

function jumpToPage(val) {
  const n = parseInt(val, 10);
  if (isNaN(n)) return;
  const page = Math.max(1, Math.min(state.totalPages, n));
  loadGroups(page);
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

// ─────────────────────────────────────────────
// セラー分析機能
// ─────────────────────────────────────────────

let sellerPollTimer = null;

function showSellerAnalysis() {
  // STEP 2 タブへ切り替え（後方互換性のため残す）
  switchStep(2);
}

// ─────────────────────────────────────────────
// スクレイピング進捗バナー
// ─────────────────────────────────────────────
let _bannerHideTimer = null;

/**
 * 画面上部バナーを更新する。
 * @param {object} opts
 *   isActive  {bool}   バナーを表示するか
 *   icon      {string} 先頭アイコン
 *   main      {string} 太字メインテキスト
 *   sub       {string} サブテキスト（薄い色）
 *   type      {string} '' | 'done' | 'stopped' | 'error'  背景色を切り替える
 *   autohide  {number} ms後に自動的に非表示 (0=しない)
 */
function updateBanner({ isActive, icon = '⚡', main = '', sub = '', type = '', autohide = 0, showLoginBtn = false } = {}) {
  const banner = document.getElementById('scrapingBanner');
  if (!banner) return;

  clearTimeout(_bannerHideTimer);

  if (!isActive) {
    banner.style.display = 'none';
    const loginBtn = document.getElementById('bannerLoginCheckBtn');
    if (loginBtn) loginBtn.style.display = 'none';
    return;
  }

  banner.style.display = '';
  banner.className = 'scraping-banner' + (type ? ` banner-${type}` : '');
  setText('bannerIcon', icon);
  setText('bannerMain', main);
  setText('bannerSub',  sub);

  // ログイン待ちボタンの表示切替（タブ移動なし）
  const loginBtn = document.getElementById('bannerLoginCheckBtn');
  if (loginBtn) loginBtn.style.display = showLoginBtn ? '' : 'none';

  if (autohide > 0) {
    _bannerHideTimer = setTimeout(() => {
      banner.style.display = 'none';
      if (loginBtn) loginBtn.style.display = 'none';
    }, autohide);
  }
}

/**
 * 「今すぐ確認して再開」ボタンの処理。
 * /api/login_check を呼びスクレイパーの待機ループを即時起動する。
 * タブ移動やページリロードは一切行わない。
 */
async function triggerLoginCheck() {
  const btn = document.getElementById('bannerLoginCheckBtn');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ 確認中...';
  }
  try {
    await fetch('/api/login_check', { method: 'POST' });
  } catch (e) {
    console.warn('ログインチェックリクエスト失敗:', e);
  }
  // ボタンは確認結果を待ってポーリングが更新するまで数秒後に戻す
  setTimeout(() => {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 今すぐ確認して再開';
    }
  }, 5000);
}

// ─────────────────────────────────────────────
// セラー分析：グループサイズ クイックフィルター
// ─────────────────────────────────────────────
function setSellerGroupFilter(minGroup) {
  state.filterMinGroup = minGroup;
  state.currentPage = 1;
  document.getElementById('filterMinGroup').value = minGroup;

  // ボタンのアクティブ状態を更新
  ['saBtnAll', 'saBtnTwo', 'saBtnThree'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) btn.classList.remove('active');
  });
  const map = { 1: 'saBtnAll', 2: 'saBtnTwo', 3: 'saBtnThree' };
  const activeId = map[minGroup] || 'saBtnAll';
  const activeBtn = document.getElementById(activeId);
  if (activeBtn) activeBtn.classList.add('active');

  loadGroups();
}

// ─────────────────────────────────────────────
// セラー分析：過去セッション読み込み
// ─────────────────────────────────────────────
async function loadSellerHistory() {
  const listEl = document.getElementById('sellerHistoryList');
  if (!listEl) return;
  listEl.innerHTML = '<span style="color:#6b7280">読み込み中...</span>';

  const data = await fetchJSON('/api/sessions?step=2');
  const sessions = data.sessions || [];

  if (sessions.length === 0) {
    listEl.innerHTML = '<span style="color:#9ca3af">Google Driveにセラー分析セッションが見つかりません</span>';
    return;
  }

  listEl.innerHTML = sessions.map(s => {
    const dis = s.is_running ? 'disabled' : '';
    const disTitle = s.is_running ? 'スクレイピング中は選択できません' : '';
    // Mac名（ホスト名）とSTEP1キーワードを組み合わせて表示ラベルを作る
    const macLabel = s.machine_name ? `💻 ${escHtml(s.machine_name)}` : '';
    const kwLabel  = s.source_keyword ? `🔑 ${escHtml(s.source_keyword)}` : '';
    const subLabel = [macLabel, kwLabel].filter(Boolean).join('　');
    return `
    <div class="session-row">
      <div class="session-row-info">
        <div class="session-row-keyword" style="font-size:12px">🏪 セラー分析${subLabel ? `<span style="margin-left:6px;color:#6b7280;font-weight:normal">${subLabel}</span>` : ''}</div>
        <div class="session-row-meta">
          <span class="meta-count">${(s.total_items || 0).toLocaleString()}件</span>
          <span class="meta-date">${escHtml(s.date_str)}</span>
          ${sessionStatusSpan(s.status)}
          ${s.is_running ? '<span class="meta-running">🔄 実行中</span>' : ''}
        </div>
      </div>
      <div class="session-row-actions">
        <button class="btn btn-secondary btn-sm"
                style="font-size:11px;padding:4px 10px;white-space:nowrap"
                title="${disTitle || '分析結果をグリッドに表示'}"
                ${dis}
                onclick="loadSessionToGrid('${escHtml(s.name)}')">📂 表示</button>
        <button class="btn-delete"
                title="このセッションを削除（復元不可）"
                onclick="deleteSession('${escHtml(s.name)}', 2)">🗑</button>
      </div>
    </div>`;
  }).join('');
}

// ─────────────────────────────────────────────
// STEP 3: 過去セッション一覧
// ─────────────────────────────────────────────
async function loadStep3History() {
  const el = document.getElementById('step3SessionsList');
  if (!el) return;
  el.innerHTML = '<span style="color:#9ca3af;font-size:13px">読み込み中...</span>';

  const data = await fetchJSON('/api/sessions?step=3');
  const sessions = data.sessions || [];

  if (sessions.length === 0) {
    el.innerHTML = '<span style="color:#9ca3af;font-size:13px">Google DriveにSTEP 3のセッションが見つかりません</span>';
    return;
  }

  el.innerHTML = sessions.map(s => {
    const dis = s.is_running ? 'disabled' : '';
    const disTitle = s.is_running ? 'スクレイピング中は選択できません' : '';
    return `
    <div class="session-row">
      <div class="session-row-info">
        <div class="session-row-keyword" style="font-size:12px">⚡ マスターセラーリサーチ</div>
        <div class="session-row-meta">
          <span class="meta-count">${(s.total_items || 0).toLocaleString()}件</span>
          <span class="meta-date">${escHtml(s.date_str)}</span>
          ${sessionStatusSpan(s.status)}
          ${s.is_running ? '<span class="meta-running">🔄 実行中</span>' : ''}
        </div>
      </div>
      <div class="session-row-actions">
        <button class="btn btn-secondary btn-sm"
                title="${disTitle || '結果をグリッドに表示'}"
                ${dis}
                onclick="loadSessionToGrid('${escHtml(s.name)}')">📂 表示</button>
        <button class="btn-delete"
                title="このセッションを削除（復元不可）"
                onclick="deleteSession('${escHtml(s.name)}', 3)">🗑</button>
      </div>
    </div>`;
  }).join('');
}

// ─────────────────────────────────────────────
// セッションをグリッドにロード（STEP 1/2/3 共通）
// ─────────────────────────────────────────────
async function loadSessionToGrid(sessionName) {
  showToast('⏳ セッションを読み込み中...');
  const res = await fetchJSON(`/api/sessions/${encodeURIComponent(sessionName)}/load`, 'POST');
  if (!res.success) {
    showToast('❌ ' + (res.message || '読み込み失敗'), 'error');
    return;
  }
  showToast(`✅ ${(res.total_items || 0).toLocaleString()}件を読み込みました`);
  await loadGroups();
  refreshCurrentSession();
}

// ─────────────────────────────────────────────
// 表示中セッションバー
// ─────────────────────────────────────────────
async function refreshCurrentSession() {
  const data = await fetchJSON('/api/current_session');
  updateCurrentSessionDisplay(data.session);
}

function updateCurrentSessionDisplay(session) {
  const bar   = document.getElementById('currentSessionBar');
  if (!bar) return;
  if (!session) { bar.style.display = 'none'; return; }
  const nameEl  = document.getElementById('currentSessionName');
  const countEl = document.getElementById('currentSessionCount');
  const { label, dateStr } = parseSessionName(session.name);
  if (nameEl)  nameEl.textContent  = `${label}（${dateStr}）`;
  if (countEl) countEl.textContent = session.total_items ? ` — ${session.total_items.toLocaleString()}件` : '';
  bar.style.display = '';
}

// ─────────────────────────────────────────────
// アクティブソース表示ヘルパー
// ─────────────────────────────────────────────

/**
 * 3つのソースボックスのうち1つをアクティブ表示にして、情報テキストを表示する。
 * @param {'sourceBox1'|'sourceBox2'|'sourceBox3'} activeId  アクティブにするボックスのID
 * @param {string} infoHtml  そのボックスに表示するHTMLテキスト（空文字で非表示）
 */
function setActiveSource(activeId, infoHtml) {
  const boxes = ['sourceBox1', 'sourceBox2', 'sourceBox3'];
  const infos = ['sourceInfo1', 'sourceInfo2', 'sourceInfo3'];

  // 全ボックスのアクティブ状態と情報をリセット
  boxes.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('source-active');
  });
  infos.forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.innerHTML = ''; el.style.display = 'none'; }
  });

  // 選択されたボックスをアクティブに
  const activeBox = document.getElementById(activeId);
  if (activeBox) activeBox.classList.add('source-active');

  // 情報テキストを対応するinfoエレメントに表示
  const infoIndex = boxes.indexOf(activeId);
  if (infoIndex >= 0 && infoHtml) {
    const infoEl = document.getElementById(infos[infoIndex]);
    if (infoEl) { infoEl.innerHTML = infoHtml; infoEl.style.display = ''; }
  }
}

// ─────────────────────────────────────────────
// セラー分析：現在のSTEP 1結果から直接セラーIDを取得（CSV不要）
// ─────────────────────────────────────────────
async function loadFromCurrentSession() {
  const btn = document.getElementById('btnFromSession');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ 取得中...'; }

  try {
    const res = await fetch('/api/seller_ids_from_current_session', { method: 'POST' });
    const data = await res.json();

    if (!res.ok || data.error) {
      showToast('❌ ' + (data.error || '取得失敗'), 'error');
      return;
    }

    const hasUrl = data.has_seller_url;
    setActiveSource('sourceBox1',
      `✅ 使用中: 現在のセッション「${escHtml(data.keyword || '—')}」（${data.count}件）`);
    document.getElementById('sellerImportSummary').textContent =
      `${data.count} 件のユニークセラーIDを取得しました（seller_url: ${hasUrl ? 'あり ✅' : 'なし ⚠ フォールバックURLを使用'}）`;

    renderSellerTable(data.sellers);
    document.getElementById('sellerImportResult').style.display = 'block';
    document.getElementById('sellerListMeta').textContent = `${data.count} 件`;
    showToast(`✅ ${data.count} 件のセラーIDを取得しました`);

  } catch (e) {
    showToast('❌ 取得に失敗しました: ' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '🔗 現在のSTEP 1結果からセラーIDを取得'; }
  }
}

async function loadLatestCsv() {
  const btn = document.getElementById('btnLoadLatest');
  btn.disabled = true;
  btn.textContent = '⏳ 読み込み中...';

  try {
    const res = await fetch('/api/latest_csv_import', { method: 'POST' });
    const data = await res.json();

    if (!res.ok || data.error) {
      showToast(data.error || '読み込み失敗', 'error');
      return;
    }

    const hasUrl = data.has_seller_url;
    const { label, dateStr } = parseSessionName(data.session_name || '');
    setActiveSource('sourceBox3',
      `✅ 使用中: 「${escHtml(label || data.session_name)}」（${dateStr}）${data.count}件`);
    document.getElementById('sellerImportSummary').textContent =
      `${data.count} 件のユニークセラーIDを読み込みました（seller_url: ${hasUrl ? 'あり ✅' : 'なし ⚠ フォールバックURLを使用'}）`;

    renderSellerTable(data.sellers);
    document.getElementById('sellerImportResult').style.display = 'block';
    document.getElementById('sellerListMeta').textContent = `${data.count} 件`;
    showToast(`最新結果から ${data.count} 件のセラーIDを読み込みました`);

  } catch (e) {
    showToast('読み込みに失敗しました: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '💾 最新の保存済みCSVを使用';
  }
}

/**
 * HTMLファイルが誤ってアップロードされた場合に警告を表示し、trueを返す。
 * 正常なCSVファイルの場合はfalseを返す。
 * ファイル名に "_iPhone_iPad用" / "_Mac用" が含まれる場合は専用のエラーメッセージを表示する。
 * @param {HTMLInputElement} input - ファイル選択 <input type="file"> 要素
 * @returns {boolean} HTMLファイルだった場合 true（呼び出し元は処理を中断すべき）、CSVなら false
 */
function validateNotHtmlFile(input) {
  const file = input.files[0];
  if (!file) return false;
  const name = file.name;
  const ext = name.split('.').pop().toLowerCase();
  if (ext !== 'html' && ext !== 'htm') return false;

  let msg;
  if (name.includes('_iPhone_iPad用')) {
    msg = '⚠️ このファイルはiPhone/iPad閲覧用のHTMLです。データの読み込みにはCSVファイルを選択してください。';
  } else if (name.includes('_Mac用')) {
    msg = '⚠️ このファイルはMac閲覧用のHTMLです。データの読み込みにはCSVファイルを選択してください。';
  } else {
    msg = '⚠️ HTMLファイルは読み込めません。CSVファイルを選択してください。';
  }

  input.value = '';
  showToast(msg, 'error');
  return true;
}

async function importSellerCsv(input) {
  const file = input.files[0];
  if (!file) return;
  if (validateNotHtmlFile(input)) return;

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/import_csv', { method: 'POST', body: formData });
    const data = await res.json();

    if (!res.ok || data.error) {
      showToast(data.error || 'CSVインポート失敗', 'error');
      return;
    }

    const hasUrl = data.has_seller_url;
    setActiveSource('sourceBox3',
      `✅ 使用中: 📁 ${escHtml(file.name)}（${data.count}件）`);
    document.getElementById('sellerImportSummary').textContent =
      `${data.count} 件のユニークセラーIDを抽出しました（seller_url: ${hasUrl ? 'あり ✅' : 'なし ⚠ フォールバックURLを使用'}）`;

    renderSellerTable(data.sellers);
    document.getElementById('sellerImportResult').style.display = 'block';
    document.getElementById('sellerListMeta').textContent = `${data.count} 件`;
    showToast(`${data.count} 件のセラーIDを読み込みました`);

  } catch (e) {
    showToast('CSVの読み込みに失敗しました: ' + e.message, 'error');
  }
}

function renderSellerTable(sellers) {
  const tbody = document.getElementById('sellerTableBody');
  if (!tbody) return;

  // URL列は表示しない（各行にボタン・リンクを置かず、一覧は表示のみ）
  // スクレイピングは「▶ スクレイピング開始」ボタン1つで全セラーを一括処理
  tbody.innerHTML = sellers.map((s, i) => {
    const statusHtml = sellerStatusBadge(s.status, s.used_count);
    return `<tr id="seller-row-${i}" style="border-bottom:1px solid #f3f4f6">
      <td style="padding:7px 12px;color:#9ca3af;font-size:12px">${i + 1}</td>
      <td style="padding:7px 12px;font-family:monospace;font-size:12px;color:#111827">${escHtml(s.seller_id)}</td>
      <td style="padding:7px 12px;text-align:center">${statusHtml}</td>
    </tr>`;
  }).join('');
}

function sellerStatusBadge(status, usedCount) {
  if (status === 'used_skip') {
    const cnt = usedCount != null ? `${usedCount}件` : '';
    return `<span style="color:#d97706;font-weight:700" title="中古${cnt}超のためスキップ">🚫 中古${cnt}超でスキップ</span>`;
  }
  const map = {
    pending: '<span style="color:#6b7280">待機中</span>',
    running: '<span style="color:#2563eb;font-weight:700">▶ 処理中</span>',
    done:    '<span style="color:#16a34a;font-weight:700">✅ 完了</span>',
    error:   '<span style="color:#dc2626;font-weight:700">❌ エラー</span>',
  };
  return map[status] || `<span>${escHtml(status)}</span>`;
}

async function startSellerScraping() {
  const res = await fetch('/api/seller_scrape/start', { method: 'POST' });
  const data = await res.json();

  if (!res.ok || data.error) {
    showToast(data.error || '開始失敗', 'error');
    return;
  }

  showToast('セラー分析スクレイピングを開始しました');
  document.getElementById('btnSellerStart').disabled = true;
  document.getElementById('btnSellerStop').disabled = false;
  document.getElementById('sellerProgressWrap').style.display = 'block';
  // 新規スクレイピング開始時に完了バナーを隠す
  const s2b = document.getElementById('step2CompletionBanner');
  if (s2b) s2b.style.display = 'none';
  // 完了後の「メイン画面で結果を見る」ボタンを非表示に
  const viewBtn = document.getElementById('btnViewSellerResult');
  if (viewBtn) viewBtn.style.display = 'none';

  clearInterval(sellerPollTimer);
  sellerPollTimer = setInterval(fetchSellerStatus, 3000);
  startGeminiStatusPolling();
}

async function stopSellerScraping() {
  await fetch('/api/seller_scrape/stop', { method: 'POST' });
  showToast('停止リクエストを送信しました');
}

async function resetSellerScraping() {
  const res = await fetch('/api/seller_scrape/reset', { method: 'POST' });
  const data = await res.json();
  if (data.error) { showToast(data.error, 'error'); return; }

  clearInterval(sellerPollTimer);
  document.getElementById('sellerImportResult').style.display = 'none';
  document.getElementById('sellerCsvInput').value = '';
  document.getElementById('sellerProgressWrap').style.display = 'none';
  document.getElementById('btnSellerStart').disabled = false;
  document.getElementById('btnSellerStop').disabled = true;
  const viewBtn = document.getElementById('btnViewSellerResult');
  if (viewBtn) viewBtn.style.display = 'none';
  // ソース表示もリセット
  setActiveSource('', '');
  showToast('リセットしました');
}

// フェーズ表示テキスト
function sellerPhaseLabel(phase, currentSeller, data) {
  switch (phase) {
    case 'scraping_list':
      return currentSeller ? `一覧取得中: ${currentSeller}` : '一覧ページ取得中...';
    case 'grouping':
      return `pHash グループ化中... (${data.total_items || 0} 件取得済み)`;
    case 'scraping_detail':
      return data.detail_pages_total > 0
        ? `詳細ページ取得中 ${data.detail_pages_done || 0} / ${data.detail_pages_total} 件`
        : '詳細ページ取得中...';
    case 'done':    return `完了 ✅ — ${data.total_items || 0} 件取得`;
    case 'stopped': return `停止 — ${data.total_items || 0} 件取得`;
    case 'error':   return 'エラーが発生しました';
    default:        return '準備中...';
  }
}

/**
 * STEP 2 セラー分析のスクレイピング進捗を取得してUIに反映する。
 * /api/seller_scrape/status をポーリング呼び出しし、
 * セラーテーブル・進捗バー・スクレイピングバナー・ボタン状態を更新する。
 * 完了または停止を検出したらポーリングタイマー（sellerPollTimer）を停止し、
 * 「メイン画面で結果を見る」ボタンを表示してグリッドをバックグラウンドで先読みする。
 * @param {boolean} [silent=false] - true のとき完了・停止時のトーストを表示しない（タブ切り替え時の静的チェックに使用）
 */
async function fetchSellerStatus(silent = false) {
  try {
    const res = await fetch('/api/seller_scrape/status');
    const data = await res.json();

    if (!data.sellers || data.sellers.length === 0) return;

    // セラーテーブル更新
    renderSellerTable(data.sellers);
    document.getElementById('sellerImportResult').style.display = 'block';
    document.getElementById('sellerListMeta').textContent = `${data.total} 件`;

    // 進捗バー: セラー単位の完了率
    if (data.total > 0) {
      const pct = Math.round((data.done / data.total) * 100);
      document.getElementById('sellerProgressWrap').style.display = 'block';
      document.getElementById('sellerProgressBar').style.width = pct + '%';
      document.getElementById('sellerProgressCount').textContent =
        `セラー ${data.done} / ${data.total} 件`;

      const currentSeller = data.current_index >= 0
        ? data.sellers[data.current_index]?.seller_id || ''
        : '';
      document.getElementById('sellerProgressLabel').textContent =
        data.running
          ? sellerPhaseLabel(data.phase, currentSeller, data)
          : sellerPhaseLabel(data.phase, '', data);
    }

    // ── 商品件数カウンター (#step2ItemCounter) ──
    const s2Counter = document.getElementById('step2ItemCounter');
    const s2Banner  = document.getElementById('step2CompletionBanner');
    const s2Count   = document.getElementById('step2CompletionCount');
    if (data.running) {
      if (s2Banner) s2Banner.style.display = 'none';
      if (s2Counter) {
        s2Counter.style.display = '';
        s2Counter.textContent = `商品取得済み: ${(data.total_items || 0).toLocaleString()}件`;
      }
    } else {
      if (s2Counter) s2Counter.style.display = 'none';
      if ((data.phase === 'done' || data.phase === 'stopped') && s2Banner && s2Count) {
        s2Count.textContent = `${(data.total_items || 0).toLocaleString()}件処理`;
        s2Banner.style.display = 'flex';
      }
    }

    // ボタン状態
    document.getElementById('btnSellerStart').disabled = data.running;
    document.getElementById('btnSellerStop').disabled = !data.running;

    // ── スクレイピングバナー更新（セラー分析用） ──
    // ログイン待ち（STEP2）
    if (data.phase === 'login_required') {
      updateBanner({
        isActive: true, icon: '⚠️', type: 'login',
        main: 'AucFanのログインが切れました',
        sub:  'Chromeで aucfan.com にログイン後、自動再開（30秒）またはボタンで即再開。',
        showLoginBtn: true,
      });
      // ヘッダーも更新してからreturn（タブは移動しない）
      const hdrElS2 = document.getElementById('headerStatus');
      if (hdrElS2) {
        hdrElS2.textContent = '⚠️ ログイン待ち';
        hdrElS2.style.background = 'rgba(255,255,255,.35)';
      }
      return;
    }
    if (data.running) {
      const currentSeller = data.current_index >= 0
        ? (data.sellers[data.current_index]?.seller_id || '') : '';
      const phaseText = sellerPhaseLabel(data.phase, currentSeller, data);
      const sellerProgress = data.total > 0
        ? `セラー ${data.done}/${data.total} 件  |  商品 ${data.total_items || 0}件取得`
        : `商品 ${data.total_items || 0}件取得`;
      updateBanner({
        isActive: true,
        main: phaseText,
        sub:  sellerProgress,
      });
    } else if (data.phase === 'done') {
      updateBanner({
        isActive: true, icon: '✅', type: 'done',
        main: 'セラー分析 完了',
        sub:  `商品 ${data.total_items || 0}件 / セラー ${data.done}件`,
        autohide: 12000,
      });
    } else if (data.phase === 'stopped') {
      updateBanner({
        isActive: true, icon: '⏹', type: 'stopped',
        main: 'セラー分析 停止',
        sub:  `商品 ${data.total_items || 0}件取得`,
        autohide: 8000,
      });
    } else if (data.phase === 'error') {
      updateBanner({
        isActive: true, icon: '❌', type: 'error',
        main: 'セラー分析 エラー',
        sub:  'ターミナルのログを確認してください',
        autohide: 15000,
      });
    }

    // 完了 or 停止時: ポーリング停止 + メイン画面更新ボタンを表示
    if (!data.running) {
      clearInterval(sellerPollTimer);
      stopGeminiStatusPolling();
      checkGeminiStatus();   // 停止直後に最終確認

      if (data.phase === 'done' || data.phase === 'stopped') {
        // 「メイン画面で結果を見る」ボタンを表示
        let viewBtn = document.getElementById('btnViewSellerResult');
        if (!viewBtn) {
          viewBtn = document.createElement('button');
          viewBtn.id = 'btnViewSellerResult';
          viewBtn.className = 'btn btn-primary btn-sm';
          viewBtn.style.marginTop = '10px';
          viewBtn.textContent = '📊 メイン画面で結果を見る';
          viewBtn.onclick = () => {
            loadGroups();  // メイングリッドを再読み込み
            showToast('セラー分析結果をメイン画面に表示しました');
          };
          document.getElementById('sellerProgressWrap').appendChild(viewBtn);
        }
        viewBtn.style.display = '';

        // メイングリッドをバックグラウンドで先読み
        loadGroups();

        if (!silent) {
          showToast(
            data.phase === 'done'
              ? `完了: 商品 ${data.total_items || 0} 件 / セラー ${data.done} 件処理`
              : `停止: 商品 ${data.total_items || 0} 件取得`
          );
        }
      }
    }

    // ── ヘッダーステータス更新（STEP2用） ──
    // SSEはSTEP1専用のため、STEP2中はここで headerStatus を直接更新する
    const sellerStatusLabels = {
      scraping_list:   '一覧取得中',
      scraping_detail: '詳細取得中',
      grouping:        'グループ化中',
      vision_check:    '🤖 Vision判定中',
      done:            '完了',
      stopped:         '停止済み',
      error:           'エラー',
      idle:            '待機中',
      login_required:  '⚠️ ログイン待ち',
    };
    const hdrEl = document.getElementById('headerStatus');
    if (hdrEl) {
      hdrEl.textContent = sellerStatusLabels[data.phase] || data.phase || '待機中';
      hdrEl.style.background = data.running ? 'rgba(255,255,255,.35)' : 'rgba(255,255,255,.15)';
    }

  } catch (e) {
    console.warn('セラーステータス取得失敗:', e);
  }
}

// ═══════════════════════════════════════════════
// STEP 3: マスターセラーリサーチ
// ═══════════════════════════════════════════════

let masterPollTimer = null;

// ─── マスターリスト取得・表示 ───
async function loadMasterSellers() {
  const [data, stats] = await Promise.all([
    fetchJSON('/api/master_sellers?sort_order=desc&limit=0'),
    fetchJSON('/api/master_sellers/stats'),
  ]);

  // ヘッダー情報更新
  if (stats) {
    setText('masterTotal', stats.total ?? '—');
    setText('masterUnscraped', stats.unscraped ?? '—');
    setText('masterLastModified',
      stats.last_modified ? `最終更新: ${stats.last_modified}` : '最終更新: —'
    );
    // 全削除ボタンは件数0のとき無効化
    const delAllBtn = document.querySelector('.master-delete-all-btn');
    if (delAllBtn) delAllBtn.disabled = (stats.total === 0);
  }

  const list = document.getElementById('masterSellerList');
  if (!list || !data || !data.sellers) return;

  if (!data.sellers.length) {
    list.innerHTML = '<span style="color:#9ca3af;font-size:13px">セラーがいません（STEP 1実行後に自動追加されます）</span>';
    updateMasterBatchPreview();
    return;
  }

  list.innerHTML = data.sellers.map(s => {
    const scraped = s.last_scraped_date
      ? `<span class="master-date">${s.last_scraped_date}</span>`
      : `<span class="master-badge-new">未</span>`;
    const cands = s.candidates_count != null
      ? `<span class="master-cands">${s.candidates_count}件</span>` : '';
    // seller_id を data 属性にエンコードして保持（クリック時に取得）
    const sidAttr = escHtml(s.seller_id);
    return `
      <div class="master-seller-row">
        <span class="master-seller-id" title="${sidAttr}">${sidAttr}</span>
        <span class="master-first-date">${s.first_seen_date || '—'}</span>
        <span class="master-scraped-label">${scraped}</span>
        ${cands}
        <span class="master-keyword">${escHtml(s.source_keyword || '')}</span>
        <button class="master-row-del-btn" title="このセラーを削除"
                onclick="deleteMasterSeller('${sidAttr}', this)">🗑</button>
      </div>`;
  }).join('');

  updateMasterBatchPreview();
}

// ─── 手動追加 ───
async function addMasterSellerManual() {
  const textarea = document.getElementById('masterAddInput');
  if (!textarea) return;
  const raw = textarea.value.trim();
  if (!raw) { showToast('セラーIDを入力してください', 'error'); return; }

  // 改行・カンマ・スペースで分割して重複除去
  const ids = [...new Set(
    raw.split(/[\n,\s]+/).map(s => s.trim()).filter(Boolean)
  )];
  if (ids.length === 0) { showToast('有効なセラーIDがありません', 'error'); return; }

  const res = await fetchJSON('/api/master_sellers/add', 'POST', { seller_ids: ids, source_keyword: '手動追加' });
  if (res.success) {
    showToast(`✅ ${res.added}件追加しました（入力${res.total}件）`);
    textarea.value = '';
    loadMasterSellers();
  } else {
    showToast('❌ ' + (res.error || '追加失敗'), 'error');
  }
}

// ─── 全件削除 ───
async function deleteAllMasterSellers() {
  const total = parseInt(document.getElementById('masterTotal')?.textContent || '0', 10);
  if (!confirm(`マスターセラーリスト（${total}件）を全て削除しますか？\nこの操作は元に戻せません。`)) return;

  const res = await fetchJSON('/api/master_sellers/all', 'DELETE');
  if (res.success) {
    showToast(`🗑 マスターリスト ${res.deleted}件を全削除しました`);
    loadMasterSellers();
  } else {
    showToast('❌ 削除失敗: ' + (res.error || '不明なエラー'), 'error');
  }
}

// ─── 個別削除 ───
async function deleteMasterSeller(sellerId, btnEl) {
  // ボタンを一時無効化（二重クリック防止）
  if (btnEl) btnEl.disabled = true;

  const res = await fetchJSON(`/api/master_sellers/${encodeURIComponent(sellerId)}`, 'DELETE');
  if (res.success) {
    // 行をフェードアウトして削除
    const row = btnEl?.closest('.master-seller-row');
    if (row) {
      row.style.transition = 'opacity .2s';
      row.style.opacity = '0';
      setTimeout(() => { row.remove(); updateMasterHeaderCount(-1); }, 220);
    }
  } else {
    showToast('❌ ' + (res.error || '削除失敗'), 'error');
    if (btnEl) btnEl.disabled = false;
  }
}

// ─── ヘッダーの合計件数をインクリメント調整（再取得不要） ───
function updateMasterHeaderCount(delta) {
  const totalEl = document.getElementById('masterTotal');
  const unscrapedEl = document.getElementById('masterUnscraped');
  if (totalEl) {
    const n = parseInt(totalEl.textContent || '0', 10) + delta;
    totalEl.textContent = Math.max(0, n);
  }
  // 全削除ボタンの有効/無効を更新
  const delAllBtn = document.querySelector('.master-delete-all-btn');
  if (delAllBtn) {
    const cur = parseInt(document.getElementById('masterTotal')?.textContent || '0', 10);
    delAllBtn.disabled = (cur === 0);
  }
}

async function updateMasterBatchPreview() {
  const stats = await fetchJSON('/api/master_sellers/stats');
  if (!stats) return;
  const unscraped = stats.unscraped || 0;
  const batchSel = document.getElementById('masterBatchSize');
  const batchSize = batchSel ? parseInt(batchSel.value, 10) : 0;
  const count = batchSize > 0 ? Math.min(batchSize, unscraped) : unscraped;
  setText('masterBatchCount', count);
}

// ─── スクレイピング開始 ───
async function startMasterScraping() {
  const sortOrder = document.querySelector('input[name="masterSortOrder"]:checked')?.value || 'desc';
  const batchSize = parseInt(document.getElementById('masterBatchSize')?.value || '0', 10);

  const data = await fetchJSON('/api/master_sellers/scrape/start', 'POST', {
    sort_order: sortOrder,
    batch_size: batchSize,
  });

  if (data.error) {
    showToast('❌ ' + data.error, 'error');
    return;
  }

  document.getElementById('btnMasterStart').disabled = true;
  document.getElementById('btnMasterStop').disabled = false;
  document.getElementById('masterProgressWrap').style.display = '';
  // 新規スクレイピング開始時に完了バナーを隠す
  const s3b = document.getElementById('step3CompletionBanner');
  if (s3b) s3b.style.display = 'none';
  showToast(`▶ STEP 3 スクレイピング開始（${data.total}件）`);

  clearInterval(masterPollTimer);
  masterPollTimer = setInterval(() => fetchMasterStatus(), 3000);
  startGeminiStatusPolling();
}

// ─── 停止 ───
async function stopMasterScraping() {
  await fetchJSON('/api/master_sellers/scrape/stop', 'POST');
  showToast('⏹ 停止中...');
}

// ─── 進捗ポーリング ───
/**
 * STEP 3 マスターセラーリサーチのスクレイピング進捗を取得してUIに反映する。
 * /api/master_sellers/scrape/status をポーリング呼び出しし、
 * 進捗バー・ラベル・現在処理中セラー名・ボタン状態を更新する。
 * 完了または停止を検出したらポーリングタイマー（masterPollTimer）を停止し、
 * マスターリスト表示とメイングリッドを再読み込みする。
 * @param {boolean} [silent=false] - true のとき完了・停止時のトーストを表示しない（タブ切り替え時の静的チェックに使用）
 */
async function fetchMasterStatus(silent = false) {
  try {
    const data = await fetchJSON('/api/master_sellers/scrape/status');
    if (!data) return;

    // ログイン待ち（STEP3）
    if (data.phase === 'login_required') {
      updateBanner({
        isActive: true, icon: '⚠️', type: 'login',
        main: 'AucFanのログインが切れました',
        sub:  'Chromeで aucfan.com にログイン後、自動再開（30秒）またはボタンで即再開。',
        showLoginBtn: true,
      });
      const hdrEl = document.getElementById('headerStatus');
      if (hdrEl) {
        hdrEl.textContent = '⚠️ ログイン待ち';
        hdrEl.style.background = 'rgba(255,255,255,.35)';
      }
      return;
    }

    const pct = data.total > 0 ? Math.round(data.done / data.total * 100) : 0;
    const bar = document.getElementById('masterProgressBar');
    if (bar) bar.style.width = pct + '%';
    setText('masterProgressLabel', phaseLabel3(data.phase));
    setText('masterProgressCount', `${data.done} / ${data.total} セラー`);
    setText('masterProgressSeller', data.current_seller ? `処理中: ${data.current_seller}` : '');

    // ── 商品件数カウンター (#step3ItemCounter) ──
    const s3Counter = document.getElementById('step3ItemCounter');
    const s3Banner  = document.getElementById('step3CompletionBanner');
    const s3Count   = document.getElementById('step3CompletionCount');
    if (data.running) {
      if (s3Banner) s3Banner.style.display = 'none';
      if (s3Counter) {
        s3Counter.style.display = '';
        s3Counter.textContent = `商品取得済み: ${(data.total_items || 0).toLocaleString()}件`;
      }
    } else {
      if (s3Counter) s3Counter.style.display = 'none';
      if ((data.phase === 'done' || data.phase === 'stopped') && s3Banner && s3Count) {
        s3Count.textContent = `${(data.total_items || 0).toLocaleString()}件処理`;
        s3Banner.style.display = 'flex';
      }
    }

    if (!data.running) {
      clearInterval(masterPollTimer);
      stopGeminiStatusPolling();
      checkGeminiStatus();   // 停止直後に最終確認
      document.getElementById('btnMasterStart').disabled = false;
      document.getElementById('btnMasterStop').disabled = true;

      if (data.phase === 'done' || data.phase === 'stopped') {
        // マスターリストを更新（scraped日付が書き込まれた後）
        loadMasterSellers();
        // グリッドにも結果を反映
        loadGroups();
        if (!silent) {
          showToast(
            data.phase === 'done'
              ? `✅ STEP 3 完了: 商品 ${data.total_items || 0}件 / セラー ${data.done}件`
              : `⏹ STEP 3 停止: 商品 ${data.total_items || 0}件取得`
          );
        }
      }
    }

    // ── ヘッダーステータス更新（STEP3用） ──
    // SSEはSTEP1専用のため、STEP3中はここで headerStatus を直接更新する
    const hdrEl3 = document.getElementById('headerStatus');
    if (hdrEl3) {
      hdrEl3.textContent = phaseLabel3(data.phase) || '待機中';
      hdrEl3.style.background = data.running ? 'rgba(255,255,255,.35)' : 'rgba(255,255,255,.15)';
    }

  } catch (e) {
    console.warn('STEP 3 ステータス取得失敗:', e);
  }
}

function phaseLabel3(phase) {
  return {
    idle: '待機中',
    scraping_list: '一覧取得中',
    grouping: 'グループ化中',
    scraping_detail: '詳細取得中',
    vision_check: 'Vision判定中',
    done: '完了',
    stopped: '停止',
    error: 'エラー',
    login_required: '⚠️ ログイン待ち',
  }[phase] || phase;
}

// ═══════════════════════════════════════════════
// グリッド CSV 読み込み（STEP 1 / 2 / 3 共通）
// ═══════════════════════════════════════════════

async function loadGridFromCsv(input) {
  const file = input.files[0];
  if (!file) return;
  if (validateNotHtmlFile(input)) return;

  const label = input.closest('label');
  const origText = label ? label.childNodes[0]?.textContent?.trim() : '';
  if (label) label.style.opacity = '0.6';
  showToast('⏳ CSV読み込み中...');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch('/api/load_csv', { method: 'POST', body: formData });
    const data = await res.json();

    if (!res.ok || data.error) {
      showToast('❌ ' + (data.error || 'CSV読み込み失敗'), 'error');
      return;
    }

    showToast(`✅ ${data.total_items.toLocaleString()} 件を読み込みました`);
    loadGroups(1);   // グリッドを再描画

  } catch (e) {
    showToast('❌ CSV読み込みエラー: ' + e.message, 'error');
  } finally {
    input.value = '';   // 同じファイルを再選択できるようにリセット
    if (label) label.style.opacity = '';
  }
}

// ═══════════════════════════════════════════════
// マスターリスト CSV 保存 / HTML 書き出し / CSV 読み込み
// ═══════════════════════════════════════════════

function exportMasterCsv() {
  window.location.href = '/api/master_sellers/export/csv';
  showToast('💾 マスターリストCSVをダウンロード中...');
}

async function exportMasterHtml() {
  showToast('⏳ HTML生成中...');
  try {
    const res = await fetch('/api/master_sellers/export/html');
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast('❌ ' + (err.error || 'HTML書き出し失敗'), 'error');
      return;
    }
    const disposition = res.headers.get('Content-Disposition') || '';
    let filename = 'sellers_master.html';
    const match = disposition.match(/filename\*?=(?:UTF-8'')?([^;]+)/i);
    if (match) filename = decodeURIComponent(match[1].replace(/"/g, '').trim());

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    showToast('✅ マスターリストHTMLを書き出しました');
  } catch (e) {
    showToast('❌ HTML書き出しエラー: ' + e.message, 'error');
  }
}

async function importMasterCsv(input) {
  const file = input.files[0];
  if (!file) return;
  if (validateNotHtmlFile(input)) return;

  const formData = new FormData();
  formData.append('file', file);
  showToast('⏳ マスターリストにインポート中...');

  try {
    const res = await fetch('/api/master_sellers/import/csv', { method: 'POST', body: formData });
    const data = await res.json();

    if (!res.ok || data.error) {
      showToast('❌ ' + (data.error || 'インポート失敗'), 'error');
      return;
    }

    showToast(
      `✅ ${data.added}件追加（ファイル内 ${data.total_in_file}件 / 合計 ${data.stats?.total ?? '?'}件）`
    );
    loadMasterSellers();   // マスターリスト表示を更新

  } catch (e) {
    showToast('❌ インポートエラー: ' + e.message, 'error');
  } finally {
    input.value = '';
  }
}

// ─── 別Macのリストをマージ ───
/**
 * 別の Mac で蓄積した sellers_master.json をアップロードしてマスターリストにマージする。
 * /api/master/merge にファイルを POST し、サーバー側で seller_id を重複排除して新規IDのみを追加する。
 * マージ結果（追加件数・スキップ件数）を画面のメッセージエリア（#masterMergeResult）に表示し、
 * マスターセラーリストを再描画する。
 * @param {HTMLInputElement} input - ファイル選択 <input type="file"> 要素（.json ファイルを期待）
 */
async function mergeMasterList(input) {
  const file = input.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append('file', file);
  showToast('⏳ マスターリストをマージ中...');

  // 結果エリアをいったん非表示にリセット
  const resultEl = document.getElementById('masterMergeResult');
  const msgEl    = document.getElementById('masterMergeMessage');
  if (resultEl) resultEl.style.display = 'none';

  try {
    const res  = await fetch('/api/master/merge', { method: 'POST', body: formData });
    const data = await res.json();

    if (!res.ok || data.error) {
      showToast('❌ ' + (data.error || 'マージ失敗'), 'error');
      return;
    }

    // 結果バナーを表示
    if (msgEl)    msgEl.textContent    = '✅ ' + data.message;
    if (resultEl) resultEl.style.display = '';

    showToast(`✅ マージ完了: ${data.message}`);
    loadMasterSellers();   // リスト表示を最新化

  } catch (e) {
    showToast('❌ マージエラー: ' + e.message, 'error');
  } finally {
    input.value = '';   // 同じファイルを再選択できるようにリセット
  }
}

// ─────────────────────────────────────────────
// Gemini 429 レート制限バナー
// ─────────────────────────────────────────────

let _geminiStatusPollTimer = null;

/**
 * Gemini API エラー状態を5秒ごとにポーリングし、レート制限などのエラーが発生した場合に
 * バナー（#geminiErrorBanner）を表示する。
 * スクレイピング開始時（startSellerScraping / startMasterScraping / updateProgressUI）から呼ばれる。
 * 既にタイマーが動作中の場合は何もしない（二重起動防止）。
 */
function startGeminiStatusPolling() {
  if (_geminiStatusPollTimer) return;   // 二重起動防止
  _geminiStatusPollTimer = setInterval(checkGeminiStatus, 5000);
}

/**
 * Gemini APIエラー監視のポーリングタイマーを停止してクリアする。
 * スクレイピング完了・停止時に呼ばれ、その直後に checkGeminiStatus() で最終確認を行う。
 */
function stopGeminiStatusPolling() {
  if (_geminiStatusPollTimer) {
    clearInterval(_geminiStatusPollTimer);
    _geminiStatusPollTimer = null;
  }
}

async function checkGeminiStatus() {
  try {
    const res = await fetch('/api/gemini_status');
    if (!res.ok) return;
    const data = await res.json();
    if (data.rate_limit_hit) {
      showGeminiErrorBanner(data.type, data.time);
    }
  } catch (e) {
    // ネットワークエラーは無視
  }
}

/** Gemini API エラーバナーを表示する（エラー種別に応じてメッセージ・色を変える）*/
function showGeminiErrorBanner(type, timeStr) {
  const banner = document.getElementById('geminiErrorBanner');
  if (!banner) return;

  // メッセージ定義
  const messages = {
    rate_limit:    { icon: '⚠️', text: 'Gemini APIレート制限超過。無料枠使い切りの可能性があります', cls: 'gemini-error-danger' },
    permission:    { icon: '🔴', text: 'Gemini APIキーの権限エラー。APIキーを確認してください',       cls: 'gemini-error-danger' },
    unavailable:   { icon: '⚠️', text: 'Gemini APIが一時的に混雑しています。しばらく待って再試行してください', cls: 'gemini-error-warn' },
    internal:      { icon: '⚠️', text: 'Gemini API内部エラーが発生しました。判定スキップで続行中',     cls: 'gemini-error-warn' },
    invalid_input: { icon: '⚠️', text: 'Gemini API入力エラー（画像不正など）。スキップして続行中',     cls: 'gemini-error-warn' },
  };
  const def = messages[type] || { icon: '⚠️', text: 'Gemini APIエラーが発生しました', cls: 'gemini-error-warn' };

  // アイコン・メッセージ・時刻をセット
  const iconEl = document.getElementById('geminiErrorIcon');
  const msgEl  = document.getElementById('geminiErrorMessage');
  const timeEl = document.getElementById('geminiErrorTime');
  if (iconEl) iconEl.textContent = def.icon;
  if (msgEl)  msgEl.textContent  = def.text;
  if (timeEl) timeEl.textContent = timeStr ? `（${timeStr} 検出）` : '';

  // 色クラスをリセットして付与
  banner.classList.remove('gemini-error-danger', 'gemini-error-warn');
  banner.classList.add(def.cls);
  banner.style.display = '';
}

/** 後方互換: 旧名 showGeminiRateLimitBanner */
function showGeminiRateLimitBanner(timeStr) {
  showGeminiErrorBanner('rate_limit', timeStr);
}

function closeGeminiErrorBanner() {
  const banner = document.getElementById('geminiErrorBanner');
  if (banner) banner.style.display = 'none';
  // サーバー側フラグもリセット
  fetch('/api/gemini_status/reset', { method: 'POST' }).catch(() => {});
}

/** 後方互換: 旧名 closeGeminiRateLimitBanner */
function closeGeminiRateLimitBanner() {
  closeGeminiErrorBanner();
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
