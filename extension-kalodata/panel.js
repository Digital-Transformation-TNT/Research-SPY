/*
 * Bảng điều khiển cho hai bộ cào Kalodata.
 *
 * Trang này KHÔNG tự gọi mạng: nó gửi `KD_PRODUCT` / `KD_VIDEO` xuống service worker và nhận
 * kết quả. Lý do không gọi thẳng từ đây: khi cookie phiên là SameSite=Lax, request khởi từ
 * trang extension không mang cookie đi và API trả về HTML đăng nhập. Service worker có sẵn
 * đường lùi chạy trong context kalodata.com — chỗ duy nhất chắc chắn có cookie.
 *
 * CỘT BẢNG SINH TỪ DỮ LIỆU THẬT, không hard-code. Field của `/product/searchList` đã xác minh,
 * nhưng `/video/searchList` thì chưa bắt được lần nào — hard-code cột cho video là đoán mò, và
 * đoán sai thì bảng trống trơn trong khi dữ liệu vẫn về đủ. Bảng tự đọc key của bản ghi thật,
 * đẩy vài cột quan trọng lên đầu, còn lại giữ nguyên thứ tự API trả.
 */

const KD_REGIONS = ['VN', 'TH', 'ID', 'PH', 'MY', 'SG', 'US', 'GB', 'JP', 'MX', 'BR', 'DE', 'FR', 'IT', 'ES'];

// Đẩy lên đầu bảng, phần còn lại theo đúng thứ tự API trả về.
const FIRST = ['image', 'country', 'id', 'product_title', 'title', 'description', 'revenue', 'revenue_raw', 'sale', 'unit_price'];
// Ẩn khỏi BẢNG: mảng dài vẽ ra thì vô nghĩa. Vẫn còn nguyên trong CSV/JSON.
const HIDE = ['revenue_trend', 'views_trend', 'average_price_trend'];

const $ = (id) => document.getElementById(id);
let kind = 'product';
let rows = [];
let stop = false;   // nút Chạy hoá thành nút Dừng khi đang lật trang

function setStatus(msg, cls) {
  $('status').textContent = msg;
  $('status').className = 'status' + (cls ? ' ' + cls : '');
}

/* ── region ─────────────────────────────────────────────────────────────── */

function drawRegions() {
  $('regions').innerHTML = KD_REGIONS
    .map((c) => `<label><input type="checkbox" value="${c}"${c === 'VN' ? ' checked' : ''}/>${c}</label>`)
    .join('');
}

function pickedRegions() {
  return [...document.querySelectorAll('#regions input:checked')].map((i) => i.value);
}

/* ── gọi background ─────────────────────────────────────────────────────── */

function ask(msg) {
  return new Promise((resolve) => {
    chrome.runtime.sendMessage(msg, (resp) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(resp || { ok: false, error: 'không có phản hồi' });
    });
  });
}

/* ── xem video ──────────────────────────────────────────────────────────────
 *
 * KHUNG NHÚNG CHÍNH THỨC CỦA TIKTOK, suy thẳng từ video id — không gọi API Kalodata, nên
 * KHÔNG tốn credit. Kalodata có `/video/detail/getVideoUrl` nhưng đó là một lượt gọi tính
 * tiền cho mỗi video, mà thứ nhận lại cũng chỉ là cái đang xem được miễn phí ở đây.
 *
 * Vì URL dựng từ id chứ không phải từ tên tài khoản, không cần biết creator là ai.
 */

// Link mở tab: tên tài khoản bịa vẫn ra đúng video (đo: `/@x/video/{id}` → HTTP 200), nên đây
// là mức nền dùng được ngay, không phải chờ mạng.
const guessUrl = (id) => `https://www.tiktok.com/@x/video/${id}`;


/**
 * oEmbed của TikTok: công khai, không cần đăng nhập, KHÔNG tốn credit Kalodata. Trả về tên
 * tài khoản thật + tiêu đề, nhờ đó link "Mở tab mới" thành URL canonical đúng chuẩn.
 * Hỏng thì thôi — link bịa ở trên vẫn mở được video.
 */
async function tiktokMeta(id) {
  const api = 'https://www.tiktok.com/oembed?url=' + encodeURIComponent(`https://www.tiktok.com/@x/video/${id}`);
  const r = await fetch(api);
  if (!r.ok) throw new Error('oembed ' + r.status);
  const j = await r.json();
  return {
    title: j.title || '',
    author: j.author_name || '',
    url: j.author_url ? `${j.author_url}/video/${id}` : guessUrl(id),
  };
}

/**
 * Ba nấc, xuống dần khi nấc trên hỏng:
 *
 *   1. LINK CỦA KALODATA (`/video/detail/getVideoUrl`) — đây mới là thứ trang họ dùng để phát
 *      ngay tại chỗ, và là nấc DUY NHẤT đã được chứng minh chạy. Không suy được từ id: thử
 *      `img.kalocdn.com/tiktok.video/{id}/*.mp4` thì 404 cả loạt, dù `cover.png` cùng thư mục
 *      vẫn 200.
 *   2. KHUNG `player/v1` CỦA TIKTOK — miễn phí nhưng bấp bênh; `embed/v2` thì trả thẳng 503
 *      "overload-protect triggered", tức khung đen thui mà không báo gì.
 *   3. MỞ TAB MỚI — luôn dùng được, để người ta không bao giờ kẹt cứng.
 */
async function openPlayer(id) {
  // Giữ id ở `dataset`: phần chữ của thẻ này bị oEmbed ghi đè thành "@tên · tiêu đề", nên đọc
  // lại id từ textContent là đọc nhầm.
  $('playerId').dataset.id = id;
  $('playerId').textContent = id;
  $('playerOpen').href = guessUrl(id);
  $('playerVideo').hidden = true;
  $('playerVideo').removeAttribute('src');
  $('playerHint').textContent = 'Đang lấy link video…';
  $('player').hidden = false;

  const res = await ask({ type: 'KD_VIDEO_URL', videoId: id });
  if ($('player').hidden || $('playerId').dataset.id !== id) return;  // đã đóng / đổi video

  if (res.ok && res.url) {
    const v = $('playerVideo');
    // Hỏng lúc phát (link hết hạn, CDN chặn) thì tụt xuống khung TikTok — chứ không đứng im
    // với một ô đen, đúng cái đã làm mất thì giờ lần trước.
    v.onerror = () => fromTiktok(id, 'link Kalodata không phát được');
    v.src = res.url;
    v.hidden = false;
    $('playerHint').textContent = 'Nguồn: Kalodata';
  } else {
    fromTiktok(id, res.error || 'Kalodata không có link');
  }

  meta(id);
}

/**
 * Nấc 2: phát trong TAB KALODATA, không phát tại chỗ.
 *
 * Khung TikTok nhúng thẳng vào trang này thì vô dụng — đo được: từ origin
 * `chrome-extension://` nó dựng vỏ rồi không tạo thẻ <video> nào, còn từ
 * `https://www.kalodata.com` thì phát bình thường. Nên thay vì cắm một cái khung đen ở đây,
 * nhờ tab Kalodata dựng lớp phủ và đưa tab đó ra trước.
 */
/**
 * Nấc 2: MOI MP4 TỪ TRANG TIKTOK rồi phát tại chỗ.
 *
 * Chậm (phải mở tab, đợi trang dựng, tải hết bytes) nhưng là đường DUY NHẤT còn lại cho video
 * ngoài kho Kalodata — mọi kiểu nhúng iframe đều đã đo là không phát. Không tốn request
 * Kalodata nào: chỉ đụng tiktok.com.
 */
async function fromTiktok(id, why) {
  $('playerVideo').hidden = true;
  $('playerVideo').removeAttribute('src');
  $('playerHint').textContent = (why ? why + ' → ' : '') + 'đang lấy video từ TikTok (mở tab ngầm, đợi vài giây)…';

  const res = await ask({ type: 'TT_VIDEO', videoId: id });
  if ($('player').hidden || $('playerId').dataset.id !== id) return;   // đã đóng / đổi video

  if (res.ok && res.dataUrl) {
    const v = $('playerVideo');
    v.onerror = () => playInTab(id, 'file tải về không phát được');
    v.src = res.dataUrl;
    v.hidden = false;
    $('playerHint').textContent = `Nguồn: TikTok (${Math.round((res.size || 0) / 1024)} KB, ${res.from})`;
    return;
  }
  playInTab(id, res.error || 'không lấy được video từ TikTok');
}

/**
 * Nấc 3: dựng lớp phủ NGAY TRONG tab kalodata.com.
 *
 * ĐÃ THỬ VÀ ĐÃ BỎ: nhúng iframe TikTok thẳng vào bảng này. Chạy `embed.js` chính chủ cho thấy
 * nó truyền trang cha qua tham số `?referrer=`, nên tưởng khai báo được là xong — nhưng đo
 * thật ở origin `chrome-extension://` (2026-09-08): script TikTok chạy trong iframe, bấm play
 * vẫn không ra hình. Khoá theo ORIGIN THẬT, tham số không cứu được. Đừng thử lại đường đó.
 */
async function playInTab(id, why) {
  $('playerVideo').hidden = true;
  $('playerVideo').removeAttribute('src');
  $('playerHint').textContent = (why ? why + ' → ' : '') + 'đang mở trong tab Kalodata…';
  const res = await ask({ type: 'KD_PLAY_IN_TAB', videoId: id });
  if (res.ok) {
    closePlayer();
    setStatus('Đã mở video trong tab Kalodata (TikTok dễ chịu hơn khi trang cha là web thật).', 'ok');
  } else {
    $('playerHint').textContent = 'Không mở được tab Kalodata: ' + (res.error || 'không rõ')
      + ' → bấm Mở tab mới ↗.';
  }
}

function meta(id) {
  // Nạp sau, không chặn khung phát: có thì link đẹp hơn, không có cũng chẳng sao.
  tiktokMeta(id)
    .then((meta) => {
      if ($('player').hidden || $('playerId').dataset.id !== id) return;  // đã đóng/đổi video
      $('playerOpen').href = meta.url;
      $('playerId').textContent = meta.author ? `@${meta.author} · ${meta.title}`.slice(0, 70) : id;
    })
    .catch(() => {});
}

function closePlayer() {
  $('player').hidden = true;
  // Gỡ nguồn chứ không chỉ ẩn đi: ẩn mà giữ src thì video vẫn phát tiếng nền.
  $('playerVideo').pause();
  $('playerVideo').removeAttribute('src');
  $('playerId').textContent = '';
}

/* ── bảng ───────────────────────────────────────────────────────────────── */

function columnsOf(list) {
  const keys = new Set();
  for (const r of list) for (const k of Object.keys(r)) keys.add(k);
  for (const h of HIDE) keys.delete(h);
  const head = FIRST.filter((k) => keys.has(k));
  const rest = [...keys].filter((k) => !head.includes(k));
  return head.concat(rest);
}

function cell(key, value) {
  if (key === 'image') return value ? `<img src="${value}" loading="lazy" alt="" />` : '';
  if (value == null) return '';
  if (Array.isArray(value)) return `[${value.length}]`;
  if (typeof value === 'object') return JSON.stringify(value).slice(0, 60);
  if (typeof value === 'number') return value.toLocaleString('vi-VN');
  return String(value);
}

function draw(list) {
  const thead = $('tbl').tHead;
  const tbody = $('tbl').tBodies[0];
  if (!list.length) {
    thead.innerHTML = '';
    tbody.innerHTML = '';
    return;
  }
  const cols = columnsOf(list);
  // Video KHÔNG có `title` — phần chữ nằm ở `description` (đo trên response thật).
  const titleKey = kind === 'product' ? 'product_title' : 'description';
  const playable = kind === 'video';

  thead.innerHTML = '<tr>' + (playable ? '<th></th>' : '') + cols.map((c) => `<th>${c}</th>`).join('') + '</tr>';
  tbody.innerHTML = list
    .map((r) => {
      const tds = cols.map((c) => {
        const cls = c === titleKey ? ' class="title"' : (typeof r[c] === 'number' ? ' class="num"' : '');
        return `<td${cls}>${cell(c, r[c])}</td>`;
      });
      const play = playable ? `<td><button class="play" data-play="${r.id}" title="Xem ngay">▶</button></td>` : '';
      return '<tr>' + play + tds.join('') + '</tr>';
    })
    .join('');
}

/* ── xuất file ──────────────────────────────────────────────────────────── */

function save(name, text, mime) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 4000);
}

function toCsv(list) {
  // CSV lấy ĐỦ mọi field, không bỏ mảng như bảng: `revenue_trend` là chuỗi doanh thu theo
  // ngày — thứ quý nhất để phân tích ngoài Excel. Mảng nối bằng '|' cho khỏi vỡ ô.
  const keys = [...new Set(list.flatMap((r) => Object.keys(r)))];
  const esc = (v) => {
    if (v == null) return '';
    const s = Array.isArray(v) ? v.join('|') : (typeof v === 'object' ? JSON.stringify(v) : String(v));
    return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  };
  const lines = [keys.join(',')];
  for (const r of list) lines.push(keys.map((k) => esc(r[k])).join(','));
  // BOM để Excel trên Windows đọc đúng tiếng Việt — thiếu nó là mở ra thành ký tự hỏng.
  return '﻿' + lines.join('\n');
}

const stamp = () => new Date().toISOString().slice(0, 16).replace(/[:T]/g, '-');

/* ── chạy ───────────────────────────────────────────────────────────────── */

async function run() {
  const regions = pickedRegions();
  if (!regions.length) {
    setStatus('Chọn ít nhất một region.', 'err');
    return;
  }

  const maxout = $('maxout').checked;
  const wanted = maxout ? 50 : (Number($('pages').value) || 1);
  const opts = {
    keyword: $('kw').value.trim(),
    days: Number($('days').value) || 30,
    pageSize: Number($('size').value) || 10,
    sort: $('sort').value || null,
    videoType: $('vtype').value,
  };

  const calls = regions.length * wanted;
  const how = maxout ? 'tới khi chạm trần gói (tối đa 50 trang/region)' : `${regions.length} region × ${wanted} trang`;
  if (calls > 6 && !confirm(`Sắp gọi tối đa ${calls} lượt searchList — ${how}.\nMỗi lượt đều trừ credit. Chạy tiếp?`)) {
    return;
  }

  stop = false;
  $('go').textContent = '■ Dừng';
  $('csv').disabled = true;
  $('json').disabled = true;
  rows = [];
  draw([]);

  const type = kind === 'product' ? 'KD_PRODUCT' : 'KD_VIDEO';
  const problems = [];
  const notes = [];
  const empties = [];

  // LẬT TỪNG TRANG MỘT thay vì giao cả job cho background. Ba cái lợi, cái nào cũng thật:
  // bảng hiện dần nên biết mình đang có gì; bấm Dừng được giữa chừng (mỗi trang là credit);
  // và chạm trần gói ở trang nào thì dừng đúng đó, không ném đi những trang đã lấy được.
  outer:
  for (let i = 0; i < regions.length; i++) {
    const country = regions[i];
    let got = 0;

    for (let page = 1; page <= wanted; page++) {
      if (stop) break outer;
      setStatus(`Đang cào ${country} (${i + 1}/${regions.length}) — trang ${page}, đã có ${rows.length} dòng…`);

      const res = await ask({ type, opts: { ...opts, country, pages: 1, startPage: page } });

      if (!res.ok) {
        problems.push(`${country}: ${res.error || 'không rõ'}`);
        break;
      }
      const batch = res.items || [];
      // `country` gắn vào từng dòng: gộp nhiều region vào một bảng mà không có cột này thì
      // không còn biết dòng nào của nước nào.
      for (const r of batch) rows.push({ country, ...r });
      got += batch.length;
      draw(rows);

      for (const n of res.notes || []) notes.push(`${country} tr.${page}: ${n}`);

      if (res.error) {
        // Chạm trần gói giữa chừng KHÔNG phải hỏng — ghi chú rồi sang region kế.
        if (res.paywall) notes.push(`${country}: hết hạn mức phân trang của gói ở trang ${page}`);
        else problems.push(`${country} tr.${page}: ${res.error}`);
        break;
      }
      // Hết dữ liệu thật sự: trang cuối bao giờ cũng ngắn hơn cỡ trang.
      // So với cỡ trang THỰC SỰ dùng: background có thể đã hạ nó khi chạm paywall, và so
      // với cỡ mình gửi đi thì trang đầy cũng bị hiểu nhầm là trang cuối.
      if (batch.length < (res.pageSize || opts.pageSize || 10)) break;
      if (typeof res.total === 'number' && got >= res.total) break;
    }

    // 0 dòng mà không lỗi là chuyện khác hẳn lỗi: gần như luôn vì keyword sai ngôn ngữ sàn
    // (gõ "tai nghe" cho TH thì không khớp gì). Nói thẳng thay vì để người dùng đoán.
    if (!got && !problems.some((p) => p.startsWith(country + ':'))) empties.push(country);
  }

  $('go').textContent = '▶ Chạy';
  $('csv').disabled = !rows.length;
  $('json').disabled = !rows.length;

  if (!rows.length) {
    // Gợi ý theo ĐÚNG tab đang mở. Lời khuyên chung chung "thử keyword khác" là vô dụng khi
    // thủ phạm thật là bộ lọc "Có gắn SP" — nó cắt sạch video organic, và với keyword hẹp thì
    // phần còn lại rất dễ bằng không.
    const hint = kind === 'video'
      ? 'Không có kết quả. Thử: đổi "Loại video" sang Tất cả, nới Số ngày, hoặc dùng keyword rộng hơn.'
      : 'Không có kết quả — thử keyword khác hoặc nới khoảng ngày.';
    setStatus(problems.length ? 'Không có dữ liệu. ' + problems.join(' · ') : hint, 'err');
    return;
  }
  const tail = (stop ? ' · đã dừng giữa chừng' : '')
    + (empties.length ? ` · 0 dòng ở ${empties.join(', ')} (thử keyword bằng ngôn ngữ bản địa)` : '')
    + (notes.length ? ' · ' + notes.join(' · ') : '')
    + (problems.length ? ' · lỗi: ' + problems.join(' · ') : '');
  setStatus(`${rows.length} dòng từ ${regions.length} region.${tail}`, problems.length ? '' : 'ok');
}

/* ── khởi động ──────────────────────────────────────────────────────────── */

function switchTo(next) {
  kind = next;
  for (const t of document.querySelectorAll('.tab')) t.classList.toggle('on', t.dataset.kind === next);
  $('legend').innerHTML = next === 'product'
    ? 'Bộ cào sản phẩm — keyword đi bằng khoá <code>query</code>'
    : 'Bộ cào video — keyword đi bằng khoá <code>title</code>';
  $('kw').placeholder = next === 'product'
    ? 'Từ khoá sản phẩm (để trống = lấy top theo bộ lọc)'
    : 'Từ khoá video (để trống = lấy top theo bộ lọc)';
  $('sort').value = '';
  $('vtypeBox').hidden = next !== 'video';
  $('ttBox').hidden = next !== 'video';
  closePlayer();
  rows = [];
  draw([]);
  $('csv').disabled = true;
  $('json').disabled = true;
  setStatus('');
}

drawRegions();
switchTo('product');
for (const t of document.querySelectorAll('.tab')) {
  t.addEventListener('click', () => switchTo(t.dataset.kind));
}
$('go').addEventListener('click', () => {
  // Đang chạy thì bấm lần nữa là DỪNG. Không disable nút: mỗi trang là một lần trừ credit,
  // nên phải cho người ta cắt ngang được chứ không chỉ ngồi nhìn.
  if ($('go').textContent.startsWith('■')) { stop = true; setStatus('Đang dừng…'); return; }
  run();
});

// Nút ▶ dựng động theo từng lượt vẽ nên bắt sự kiện ở thân bảng, khỏi gắn lại sau mỗi lần.
$('tbl').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-play]');
  if (btn) openPlayer(btn.dataset.play);
});
/**
 * XEM VIDEO NGOÀI KHO KALODATA — tốn 0 request.
 *
 * Gói hiện tại chỉ cho 10 lượt tìm kiếm/ngày, nên phần lớn video cần xem là video KHÔNG do
 * bảng này cào ra. Với chúng thì `getVideoUrl` vô nghĩa (Kalodata không có link cho video
 * ngoài kho), nên đi thẳng nấc 2: mượn origin kalodata.com để dựng khung TikTok.
 *
 * Nấc 2 KHÔNG gọi API Kalodata lần nào — chỉ mở/dùng lại một tab trên miền đó. Hạn mức
 * 10 request/ngày không bị đụng tới.
 */
$('ttgo').addEventListener('click', () => {
  const raw = $('tturl').value.trim();
  // Chấp cả link đầy đủ, link rút gọn đã mở, lẫn id dán trần.
  const m = raw.match(/\/video\/(\d{6,})/) || raw.match(/(\d{15,})/);
  if (!m) { setStatus('Không đọc được video id từ chuỗi vừa dán.', 'err'); return; }
  $('playerId').dataset.id = m[1];
  $('playerId').textContent = m[1];
  $('playerOpen').href = guessUrl(m[1]);
  $('playerHint').textContent = '';
  $('player').hidden = false;
  meta(m[1]);
  fromTiktok(m[1], 'video ngoài kho Kalodata');
});
$('tturl').addEventListener('keydown', (e) => { if (e.key === 'Enter') $('ttgo').click(); });

$('playerClose').addEventListener('click', closePlayer);
$('player').querySelector('.backdrop').addEventListener('click', closePlayer);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('player').hidden) closePlayer(); });
$('kw').addEventListener('keydown', (e) => { if (e.key === 'Enter') run(); });
$('csv').addEventListener('click', () => save(`kalodata-${kind}-${stamp()}.csv`, toCsv(rows), 'text/csv;charset=utf-8'));
$('json').addEventListener('click', () => save(`kalodata-${kind}-${stamp()}.json`, JSON.stringify(rows, null, 2), 'application/json'));
$('check').addEventListener('click', async () => {
  setStatus('Đang kiểm tra phiên…');
  const r = await ask({ type: 'KD_STATUS' });
  setStatus(
    r.ok ? `Đã đăng nhập (đường ${r.via === 'sw' ? 'trực tiếp' : 'qua tab'}).` : `Chưa dùng được: ${r.error || 'không rõ'}`,
    r.ok ? 'ok' : 'err'
  );
});
