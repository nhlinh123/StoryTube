/* StoryTube UI — vanilla JS, không build step. */

const app = {
  state: null,
  project: null,
  tab: 'story',
  ratios: new Set(['9:16']),
  jobTimer: null,
  lastJob: null,
  lastBeatId: null,
  videoId: null,
  pendingVoice: null,
  analysis: null,
  bgVideos: [],
  settings: null,
  openChapters: new Set(),
};

/* ----------------------------- helpers ----------------------------- */
async function api(path, opts = {}) {
  const res = await fetch(path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(message, isError = false) {
  const box = document.createElement('div');
  box.className = 'toast' + (isError ? ' err' : '');
  box.textContent = message;
  document.getElementById('toasts').appendChild(box);
  setTimeout(() => box.remove(), isError ? 9000 : 4200);
}

function fmtDur(ms) {
  const s = Math.round((ms || 0) / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function fmtSize(bytes) {
  if (!bytes) return '—';
  const mb = bytes / 1048576;
  return mb >= 1 ? mb.toFixed(1) + ' MB' : Math.round(bytes / 1024) + ' KB';
}

function q(sel, root = document) { return root.querySelector(sel); }

function artUrl(art) {
  if (!art || !app.project) return '';
  return '/media/projects/' + app.project.project.slug + '/' + String(art).replace(/\\/g, '/');
}

function projectProse() {
  return ((app.project && app.project.chapters) || [])
    .flatMap(c => (c.beats || []).map(b => b.prose || ''))
    .filter(Boolean)
    .join('\n\n');
}

async function loadBgVideos() {
  try {
    const res = await api('/api/assets/videos');
    app.bgVideos = res.videos || [];
    app.bgDir = res.dir || '';
  } catch (err) {
    app.bgVideos = [];
  }
  return app.bgVideos;
}

function bgOptionsHtml(selected) {
  const list = app.bgVideos || [];
  if (!list.length) return '<option value="">(chưa có video trong thư mục nền)</option>';
  return list.map(v =>
    `<option value="${esc(v.name)}" ${v.name === selected ? 'selected' : ''}>${esc(v.name)} · ${fmtDur(v.duration_ms)}</option>`
  ).join('');
}

async function populateAutopilot() {
  await loadBgVideos();
  const chapters = (app.project && app.project.chapters) || [];
  const chapterSel = q('#ap-chapter');
  chapterSel.innerHTML = chapters.map(c =>
    `<option value="${c.id}">Chương ${c.idx} — ${esc(c.title)}</option>`).join('')
    || '<option value="">(chưa có chương)</option>';
  q('#ap-voice').innerHTML = app.state.config.voices.map(v =>
    `<option value="${v.name}" ${v.name === (app.pendingVoice || app.state.config.default_voice) ? 'selected' : ''}>${esc(v.label)}</option>`).join('');
  q('#ap-bg-file').innerHTML = bgOptionsHtml(app.bgVideos[0]?.name);

  const spec = (currentVideo() || {}).spec || {};
  if (spec.background?.mode) q('#ap-bg').value = spec.background.mode;
  if (spec.background?.source) q('#ap-bg-source').value = spec.background.source;
  if (spec.background?.file) q('#ap-bg-file').value = spec.background.file;
  if (spec.overlay) {
    q('#ap-opacity').value = spec.overlay.opacity ?? 0.5;
    q('#ap-color').value = spec.overlay.color || '#000000';
  }
  if (spec.caption?.position) q('#ap-pos').value = spec.caption.position;
  if (spec.ratios?.length) q('#ap-ratios').value = spec.ratios.join(',');

  const sync = () => {
    const src = q('#ap-source').value;
    q('#ap-text-wrap').style.display = src === 'text' ? '' : 'none';
    q('#ap-chapter').disabled = src !== 'chapter';
    const mode = q('#ap-mode').value;
    const split = q('#ap-split').value === '1';
    q('#ap-syllables').disabled = !split || mode === 'shorten';
    q('#ap-target').disabled = mode !== 'shorten';
    const bg = q('#ap-bg').value;
    q('#ap-bgfile-wrap').style.display = bg === 'video' ? '' : 'none';
    q('#ap-bg-source').disabled = bg !== 'video';
    q('#ap-bg-file').disabled = bg !== 'video' || q('#ap-bg-source').value !== 'fixed';
    q('#ap-note').textContent = mode === 'shorten'
      ? 'Rút gọn: AI viết lại kịch bản ngắn hơn theo số cảnh đề xuất — tốn token.'
      : 'Giữ nguyên văn: cắt cảnh bằng code trên đúng chữ bạn viết — không gọi AI, 0 token.';
  };
  ['#ap-source', '#ap-mode', '#ap-split', '#ap-bg', '#ap-bg-source'].forEach(sel => {
    const el = q(sel);
    if (el) el.onchange = sync;
  });
  sync();
}

/* ----------------------------- boot ----------------------------- */
async function boot() {
  try {
    app.state = await api('/api/state');
  } catch (err) {
    document.getElementById('view').innerHTML = `<div class="empty">Không gọi được API: ${esc(err.message)}</div>`;
    return;
  }
  renderSidebar();
  renderTabs();
  renderSystemInfo();
  const first = app.state.projects[0];
  if (first) await openProject(first.id);
  else renderEmptyProject();
  pollJobs(true);
}

function renderSystemInfo() {
  const cfg = app.state.config;
  const bits = [
    cfg.ffmpeg ? '<span class="chip ok">ffmpeg ✓</span>' : '<span class="chip bad">thiếu ffmpeg</span>',
    cfg.llm_ready ? '<span class="chip ok">DeepSeek ✓</span>' : '<span class="chip warn">chưa có key AI</span>',
    cfg.eleven_ready ? '<span class="chip ok">ElevenLabs ✓</span>' : '<span class="chip warn">chưa có key EL</span>',
  ];
  document.getElementById('sysinfo').innerHTML = bits.join(' ');
}

function renderSidebar() {
  const list = document.getElementById('project-list');
  const projects = app.state.projects || [];
  list.innerHTML = projects.map(p => `
    <div class="project-item ${app.project && app.project.project.id === p.id ? 'active' : ''}" data-act="open-project" data-id="${p.id}">
      <b>${esc(p.title)}</b>
      <small>${esc(p.genre || 'chưa rõ thể loại')} · ${p.counts?.scenes || 0} cảnh · ${p.counts?.renders || 0} video</small>
    </div>`).join('') || '<p class="hint">Chưa có truyện nào. Bấm “Truyện mới”.</p>';
}

function renderTabs() {
  const tabs = [['story', 'Truyện'], ['script', 'Kịch bản'], ['video', 'Video'], ['insights', 'AI log']];
  document.getElementById('tabs').innerHTML = app.project
    ? tabs.map(([key, label]) => `<div class="tab ${app.tab === key ? 'active' : ''}" data-act="tab" data-id="${key}">${label}</div>`).join('')
    : '';
}

async function openProject(id) {
  const data = await api(`/api/projects/${id}`);
  const sameProject = !!(app.project && app.project.project.id === id);
  const scrollY = window.scrollY || 0;
  if (!sameProject) app.analysis = null;
  app.project = data;

  if (!sameProject) {
    // lần đầu mở truyện: bung chương đầu
    app.openChapters = new Set(data.chapters.slice(0, 1).map(c => c.id));
  } else {
    // refresh sau khi AI viết / lưu: giữ nguyên các chương đang mở
    const alive = new Set(data.chapters.map(c => c.id));
    app.openChapters = new Set([...app.openChapters].filter(cid => alive.has(cid)));
    if (!app.openChapters.size && data.chapters.length) {
      app.openChapters.add(data.chapters[0].id);
    }
  }

  const video = data.videos[0];
  const spec = video?.spec || {};
  app.ratios = new Set(spec.ratios || ['9:16']);
  if (!app.bgVideos.length) await loadBgVideos();
  // giữ bản dựng đang chọn nếu còn tồn tại
  if (!data.videos.some(v => v.id === app.videoId)) {
    app.videoId = data.videos[0]?.id || null;
  }
  renderSidebar();
  renderTabs();
  render();
  // giữ vị trí đang đọc, tránh nhảy lên đầu trang sau mỗi lần lưu
  if (sameProject && scrollY > 0) {
    requestAnimationFrame(() => window.scrollTo(0, scrollY));
  }
}

function renderEmptyProject() {
  document.getElementById('project-title').textContent = 'Chưa có truyện';
  document.getElementById('project-meta').innerHTML = '';
  document.getElementById('topbar-actions').innerHTML = '<button data-act="open-settings">Cài đặt</button>';
  document.getElementById('view').innerHTML = `
    <div class="empty">
      <p><b>StoryTube</b> quản lý truyện, lời đọc và video trong một chỗ.</p>
      <p>1. Tạo truyện và nhập ý tưởng → 2. để AI dựng kinh thánh + dàn ý → 3. viết beat → 4. chuyển thể thành cảnh → 5. lồng tiếng và dựng 9:16, 1:1, 16:9.</p>
      <p style="margin-top:18px"><button class="primary" data-act="new-project">+ Truyện mới</button></p>
    </div>`;
}

/* ----------------------------- render ----------------------------- */
function render() {
  const p = app.project;
  if (!p) return renderEmptyProject();
  const project = p.project;
  document.getElementById('project-title').textContent = project.title;
  document.getElementById('project-meta').innerHTML = [
    `<span>${esc(project.genre || 'chưa rõ thể loại')}</span>`,
    `<span>${p.stats.chapters} chương</span>`,
    `<span>${p.stats.words} chữ</span>`,
    `<span>${p.stats.scenes} cảnh</span>`,
    `<span>${p.stats.duration_text} lời đọc</span>`,
  ].join('');
  document.getElementById('topbar-actions').innerHTML = `
    <select id="level-select" title="Cấp AI" style="width:auto">
      ${[1, 2, 3, 4, 5].map(n => `<option value="${n}" ${project.level == n ? 'selected' : ''}>Cấp ${n}</option>`).join('')}
    </select>
    <button data-act="open-settings">Cài đặt</button>
    ${project.level >= 5 ? '<button class="primary" data-act="run-pipeline">Chạy cả pipeline</button>' : ''}`;
  q('#level-select').onchange = async (e) => {
    await api(`/api/projects/${project.id}`, { method: 'PATCH', body: { level: Number(e.target.value) } });
    await openProject(project.id);
    toast('Đã đổi cấp AI');
  };
  const view = document.getElementById('view');
  if (app.tab === 'story') view.innerHTML = viewStory();
  if (app.tab === 'script') view.innerHTML = viewScript();
  if (app.tab === 'video') view.innerHTML = viewVideo();
  if (app.tab === 'insights') view.innerHTML = viewInsights();
  bindEditors();
}

/* ----------------------------- story tab ----------------------------- */
function viewStory() {
  const p = app.project;
  const project = p.project;
  const meta = project.meta ? JSON.parse(project.meta || '{}') : {};
  const premise = meta.premise || {};
  const entities = p.entities || [];
  const chars = entities.filter(e => e.kind === 'character');
  const locs = entities.filter(e => e.kind === 'location');
  const rules = entities.filter(e => e.kind === 'rule');

  const entityCard = (title, rows) => rows.length ? `
    <div style="margin-top:12px">
      <div class="hint" style="text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">${title}</div>
      ${rows.map(e => `<div class="entity"><b>${esc(e.name)}</b><p>${esc(e.summary || '')}</p></div>`).join('')}
    </div>` : '';

  const bible = `
    <div class="card">
      <h3>Kinh thánh truyện</h3>
      ${premise.logline ? `<p class="hint" style="margin-bottom:10px">${esc(premise.logline)}</p>` : ''}
      ${premise.hook_line ? `<p class="hint">Hook: <b style="color:var(--accent)">“${esc(premise.hook_line)}”</b></p>` : ''}
      ${entities.length ? '' : '<p class="hint">Chưa có nhân vật. Để AI dựng từ logline, hoặc viết tay trong dàn ý.</p>'}
      ${entityCard('Nhân vật', chars)}
      ${entityCard('Bối cảnh', locs)}
      ${entityCard('Luật truyện', rules)}
      <div class="row wrap" style="margin-top:14px">
        <button class="small" data-act="ai-premise">Dựng ý tưởng</button>
        <button class="small" data-act="ai-bible">Dựng kinh thánh</button>
      </div>
    </div>`;

  const chapters = p.chapters || [];
  const chapterHtml = chapters.map(ch => {
    const open = app.openChapters.has(ch.id);
    const beats = (ch.beats || []).map(b => `
      <div class="beat">
        <div class="beat-head">
          <b style="font-size:12.5px">${esc(b.summary || '(chưa có tóm tắt)')}</b>
          ${b.id === app.lastBeatId ? '<span class="chip warn">vừa viết</span>' : ''}
          <span class="grow"></span>
          <small>${b.words || 0} chữ</small>
          ${b.prose ? `<button class="small ghost" data-act="polish-beat" data-id="${b.id}">Mài câu</button>` : ''}
          <button class="small ${b.prose ? '' : 'primary'}" data-act="write-beat" data-id="${b.id}">${b.prose ? 'Viết lại' : 'AI viết'}</button>
        </div>
        <textarea data-editor="beat" data-id="${b.id}" placeholder="Văn xuôi của beat…">${esc(b.prose || '')}</textarea>
      </div>`).join('') || '<p class="hint">Chưa có beat. Bấm “Chia beat” để AI tách chương.</p>';

    return `
      <div class="chapter ${open ? 'open' : ''}">
        <div class="chapter-head" data-act="toggle-chapter" data-id="${ch.id}">
          <span class="idx">${String(ch.idx).padStart(2, '0')}</span>
          <b>${esc(ch.title)}</b>
          <span class="grow"></span>
          <span class="chip">${(ch.beats || []).length} beat</span>
          <span class="chip ${ch.scene_count ? 'ok' : ''}">${ch.scene_count ? ch.scene_count + ' cảnh' : 'chưa có cảnh'}</span>
          <button class="small" data-act="chapter-video" data-id="${ch.id}" title="Tạo bản dựng riêng cho chương này">Video</button>
        </div>
        <div class="chapter-body">
          <p class="synopsis">${esc(ch.synopsis || 'Chưa có tóm tắt.')}</p>
          ${ch.hook ? `<p class="hint" style="margin-bottom:10px">Móc cuối chương: “${esc(ch.hook)}”</p>` : ''}
          ${beats}
          <div class="row" style="margin-top:8px">
            <button class="small" data-act="gen-beats" data-id="${ch.id}">Chia beat</button>
          </div>
        </div>
      </div>`;
  }).join('');

  return `
    <div class="grid two">
      ${bible}
      <div class="card">
        <div class="row">
          <h3 style="margin:0">Dàn ý & văn xuôi</h3>
          <span class="grow"></span>
          <button class="small primary" data-act="open-autopilot">⚡ Tự động ra video</button>
          <button class="small" data-act="ai-outline">Lập dàn ý</button>
        </div>
        <div style="margin-top:12px">
          ${chapterHtml || '<p class="hint">Chưa có chương nào. Bấm “Lập dàn ý” để AI chia chương từ ý tưởng.</p>'}
        </div>
      </div>
    </div>`;
}

/* ----------------------------- script tab ----------------------------- */
function currentVideo() {
  const vids = (app.project && app.project.videos) || [];
  if (!vids.length) return null;
  return vids.find(v => v.id === app.videoId) || vids[0];
}

function videoScenes(video) {
  const ids = new Set(video?.scene_ids || []);
  return ((app.project && app.project.scenes) || []).filter(s => ids.has(s.id));
}

function videoPickerHtml() {
  const vids = (app.project && app.project.videos) || [];
  if (vids.length < 2) return '';
  const cur = currentVideo();
  return `<select id="video-picker" style="width:auto;max-width:320px" title="Chọn bản dựng">
    ${vids.map(v => `<option value="${v.id}" ${v.id === cur?.id ? 'selected' : ''}>${esc(v.title)}</option>`).join('')}
  </select>`;
}

function viewScript() {
  const p = app.project;
  const video = currentVideo();
  const spec = video?.spec || {};
  const scenes = videoScenes(video);
  const chapters = p.chapters || [];
  const chapterById = new Map(chapters.map(c => [c.id, c]));
  const voice = spec.voice_profile || app.pendingVoice || app.state.config.default_voice;
  const voiced = scenes.filter(s => s.status === 'voiced').length;
  const totalMs = scenes.reduce((sum, s) => sum + (s.duration_ms || 0), 0);

  const voiceOptions = app.state.config.voices.map(v =>
    `<option value="${v.name}" ${voice === v.name ? 'selected' : ''}>${esc(v.label)}</option>`).join('');

  const rows = scenes.map((s, i) => {
    const chap = s.chapter_id ? chapterById.get(s.chapter_id) : null;
    return `
    <div class="scene-row">
      <div class="num">${String(i + 1).padStart(2, '0')}</div>
      <div>
        <textarea data-editor="narration" data-id="${s.id}" placeholder="Lời đọc cho cảnh này…">${esc(s.narration)}</textarea>
        <input type="text" data-editor="on_screen" data-id="${s.id}" value="${esc(s.on_screen || '')}" placeholder="Chữ to trên hình (hook)" style="margin-top:6px">
        <div style="margin-top:6px"><span class="chip">${chap ? 'C' + chap.idx + ' · ' + esc(chap.title) : 'toàn truyện'}</span></div>
      </div>
      <div>
        <input type="text" data-editor="visual_prompt" data-id="${s.id}" value="${esc(s.visual_prompt || '')}" placeholder="Mô tả hình ảnh">
        <input type="text" data-editor="art" data-id="${s.id}" value="${esc(s.art || '')}" placeholder="ảnh nền: assets/anh.jpg" style="margin-top:6px">
      </div>
      <div class="meta">
        ${s.art ? `<img src="${artUrl(s.art)}" alt="ảnh cảnh" style="width:72px;height:96px;object-fit:cover;border-radius:6px;border:1px solid var(--line)">` : ''}
        <span class="chip ${s.status === 'voiced' ? 'ok' : ''}">${s.status === 'voiced' ? 'có tiếng' : 'chưa tiếng'}</span>
        <span>${fmtDur(s.duration_ms)}</span>
      </div>
      <div class="meta">
        <button class="small" data-act="scene-image" data-id="${s.id}">${s.art ? 'Ảnh lại' : 'Tạo ảnh'}</button>
        <button class="small ghost" data-act="del-scene" data-id="${s.id}">Xoá</button>
      </div>
    </div>`;
  }).join('');

  const scopeOptions = [
    `<option value="">Toàn truyện (${chapters.length} chương)</option>`,
    ...chapters.map(c => `<option value="${c.id}">Chương ${c.idx} — ${esc(c.title)}${c.scene_count ? ` (đã có ${c.scene_count} cảnh)` : ''}</option>`),
  ].join('');

  return `
    <div class="card">
      <div class="row wrap">
        ${videoPickerHtml()}
        <select id="script-scope" style="width:auto;max-width:300px" title="Phạm vi">${scopeOptions}</select>
        <select id="script-mode" style="width:auto" title="Cách tạo cảnh">
          <option value="verbatim">Giữ nguyên văn (0 token)</option>
          <option value="shorten">Rút gọn bằng AI</option>
        </select>
        <select id="script-split" style="width:auto" title="Chia cảnh">
          <option value="1">Chia cảnh</option>
          <option value="0">1 cảnh duy nhất</option>
        </select>
        <span style="width:78px"><input type="number" id="script-syllables" value="32" min="12" max="120" title="Âm tiết mỗi cảnh (chia cảnh giữ nguyên văn)"></span>
        <span style="width:70px"><input type="number" id="scenes-target" value="${app.analysis ? app.analysis.scope.suggested_scenes : 8}" min="2" max="60" title="Số cảnh (khi rút gọn bằng AI)"></span>
        <button data-act="gen-script">Tạo cảnh</button>
        <span class="grow"></span>
        <select id="voice-select" style="width:auto;min-width:210px" title="Giọng đọc của bản dựng này">${voiceOptions}</select>
        <button class="ghost small" data-act="add-scene">+ Cảnh</button>
        <button class="primary small" data-act="voice-all">Lồng tiếng tất cả</button>
      </div>
      <div class="row wrap" style="margin-top:8px">
        <span class="hint">Độ dài mỗi video:</span>
        <select id="analyze-target" style="width:auto" title="Độ dài video mục tiêu">
          ${[[45, '45 giây'], [60, '60 giây'], [90, '90 giây'], [120, '2 phút'], [180, '3 phút']]
            .map(([v, l]) => `<option value="${v}" ${(app.analysis ? app.analysis.target_seconds : 90) === v ? 'selected' : ''}>${l}</option>`).join('')}
        </select>
        <button class="small" data-act="analyze">Phân tích truyện → số cảnh</button>
        <span class="hint">Đo độ dài thật của từng chương rồi tính số cảnh/tập. Không tốn token.</span>
      </div>
      <p class="hint" style="margin:10px 0 0">
        ${video ? `Bản dựng <b>${esc(video.title)}</b> · ${scenes.length} cảnh · ${fmtDur(totalMs)} · ${voiced}/${scenes.length} có tiếng` : 'Chưa có bản dựng nào — bấm “Chuyển thể từ truyện” để tạo.'}
        · Đổi giọng ở đây là đổi luôn cho bản dựng (đồng bộ với tab Video).
      </p>
    </div>
    ${app.analysis ? analysisBox(app.analysis) : ''}
    <details class="card" style="margin-top:10px">
      <summary class="hint" style="cursor:pointer">Dán văn bản nguồn (truyện viết ở nơi khác, hoặc xuất từ xnovelist)</summary>
      <textarea id="script-source" rows="5" style="margin-top:10px" placeholder="Dán truyện ngắn / chương vào đây rồi bấm “Chuyển thể từ truyện”…"></textarea>
    </details>
    <div class="card" style="margin-top:14px;padding:0;overflow:hidden">
      ${rows || '<div class="empty">Bản dựng chưa có cảnh. Chọn phạm vi rồi bấm “Chuyển thể từ truyện”.</div>'}
    </div>`;
}

function analysisBox(a) {
  const rows = a.per_chapter.map(c => `
    <tr style="border-top:1px solid var(--line)">
      <td style="padding:6px 4px" class="mono">C${c.idx}</td>
      <td style="padding:6px 4px">${esc(c.title)}</td>
      <td style="padding:6px 4px" class="mono">${c.words}</td>
      <td style="padding:6px 4px" class="mono">${fmtDur(c.read_seconds * 1000)}</td>
      <td style="padding:6px 4px" class="mono">${c.episodes}</td>
      <td style="padding:6px 4px" class="mono">${c.scenes_per_episode || '—'}</td>
      <td style="padding:6px 4px">${c.scene_count ? `<span class="chip ok">đã có ${c.scene_count} cảnh</span>` : ''}</td>
    </tr>`).join('');

  return `
    <div class="card" style="margin-top:10px">
      <div class="row wrap">
        <h3 style="margin:0">Phân tích truyện</h3>
        <span class="grow"></span>
        <span class="chip">${a.totals.read_text} lời đọc</span>
        <span class="chip">${a.totals.words} chữ</span>
        <span class="chip">video ${a.target_seconds}s</span>
        <button class="small primary" data-act="apply-analysis">Dùng ${a.scope.suggested_scenes} cảnh</button>
        <button class="small ghost" data-act="clear-analysis">Ẩn</button>
      </div>
      <p class="hint" style="margin:10px 0">${esc(a.message)}</p>
      <div class="row wrap" style="gap:10px;margin-bottom:8px">
        <span class="chip">Cô đọng: <b>${a.plans.condensed.episodes}</b> tập × ${a.plans.condensed.scenes_per_episode} cảnh</span>
        <span class="chip">Giữ chi tiết: <b>${a.plans.full.episodes}</b> tập × ${a.plans.full.scenes_per_episode} cảnh</span>
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:12px">
        <thead><tr style="color:var(--muted);text-align:left">
          <th style="padding:4px">#</th><th>Chương</th><th>Chữ</th><th>Lời đọc</th><th>Tập</th><th>Cảnh/tập</th><th></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

/* ----------------------------- video tab ----------------------------- */
function viewVideo() {
  const p = app.project;
  const video = currentVideo();
  const spec = video?.spec || {};
  const caption = spec.caption || {};
  const ratios = app.state.config.ratios;
  const renders = video?.renders || [];
  const vscenes = videoScenes(video);
  const withArt = vscenes.filter(s => s.art).length;
  const voiced = vscenes.filter(s => s.status === 'voiced').length;
  const totalMs = vscenes.reduce((sum, s) => sum + (s.duration_ms || 0), 0);
  const imageModels = app.state.config.image_models || [];
  const imageModel = app.state.config.image_model || imageModels[0] || '';
  const noScenes = !vscenes.length;
  const bgSpec = spec.background || {};
  const overlay = spec.overlay || {};

  const ratioHtml = ratios.map(r => {
    const on = app.ratios.has(r.key);
    return `<label class="ratio-opt ${on ? 'on' : ''}">
      <input type="checkbox" data-ratio="${r.key}" ${on ? 'checked' : ''}>
      <span><b>${r.key}</b><small>${r.w}×${r.h} · ${esc(r.label)}</small></span>
    </label>`;
  }).join('');

  const renderHtml = renders.map(r => `
    <div class="render-card">
      ${r.status === 'done' && r.url
        ? `<video src="${r.url}" controls preload="metadata" ${r.thumb_url ? `poster="${r.thumb_url}"` : ''}></video>`
        : `<div class="empty" style="padding:30px 10px">${r.status === 'error' ? 'Lỗi: ' + esc((r.error || '').slice(0, 120)) : 'Đang dựng…'}</div>`}
      <div class="info">
        <span>${esc(r.ratio)} · ${fmtDur(r.duration_ms)} · ${fmtSize(r.bytes)}</span>
        ${r.url ? `<a href="${r.url}?download=1" download><button class="small ghost">Tải</button></a>` : ''}
      </div>
    </div>`).join('');

  const sceneList = vscenes.slice(0, 10).map((s, i) => `
    <div class="hint" style="display:flex;gap:8px;align-items:center;padding:3px 0;border-top:1px dashed #1a2332">
      <span class="mono" style="width:22px;color:var(--muted)">${String(i + 1).padStart(2, '0')}</span>
      <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(s.title || s.narration || '(trống)')}</span>
      <span class="mono">${fmtDur(s.duration_ms)}</span>
      <span class="chip ${s.status === 'voiced' ? 'ok' : ''}" style="font-size:10px">${s.status === 'voiced' ? 'tiếng' : '—'}</span>
      <span class="chip ${s.art ? 'ok' : ''}" style="font-size:10px">${s.art ? 'ảnh' : '—'}</span>
    </div>`).join('');

  return `
    <div class="card" style="margin-bottom:14px">
      <div class="row wrap">
        ${videoPickerHtml()}
        <button class="small ghost" data-act="new-video">+ Bản dựng mới</button>
        <span class="grow"></span>
        <span class="chip">${vscenes.length} cảnh</span>
        <span class="chip">${fmtDur(totalMs)}</span>
        <span class="chip ${voiced === vscenes.length && vscenes.length ? 'ok' : 'warn'}">${voiced}/${vscenes.length} có tiếng</span>
        <span class="chip ${withArt === vscenes.length && vscenes.length ? 'ok' : ''}">${withArt}/${vscenes.length} có ảnh</span>
      </div>
      ${noScenes
        ? `<div class="empty" style="padding:22px 10px">Bản dựng này chưa có cảnh.<br>
             Vào tab <b>Kịch bản</b>, chọn phạm vi (toàn truyện hoặc một chương) rồi bấm “Chuyển thể từ truyện”,<br>
             hoặc bấm <b>Tạo video từ chương</b> trong tab Truyện.</div>`
        : `<div style="margin-top:10px">${sceneList}
             ${vscenes.length > 10 ? `<div class="hint" style="padding-top:6px">… và ${vscenes.length - 10} cảnh nữa (xem đầy đủ ở tab Kịch bản)</div>` : ''}
           </div>`}
    </div>

    <div class="grid two">
      <div class="card">
        <h3>Thiết lập bản dựng</h3>
        <label>Giọng đọc</label>
        <select id="video-voice">
          ${app.state.config.voices.map(v => `<option value="${v.name}" ${(spec.voice_profile === v.name) ? 'selected' : ''}>${esc(v.label)}</option>`).join('')}
        </select>

        <label style="margin-top:10px">Kiểu phụ đề</label>
        <select id="video-caption">
          ${[['karaoke', 'Karaoke từng từ'], ['block', 'Khối câu'], ['beast', 'Beast (to, dằn)'], ['minimal', 'Tối giản']]
            .map(([k, l]) => `<option value="${k}" ${((caption.name || 'karaoke') === k) ? 'selected' : ''}>${l}</option>`).join('')}
        </select>

        <label style="margin-top:10px">Watermark / handle</label>
        <input type="text" id="video-watermark" value="${esc(spec.watermark || '')}" placeholder="@kenhtruyen">

        <div class="form-grid" style="margin-top:10px">
          <label style="display:flex;gap:8px;align-items:center;color:var(--text)"><input type="checkbox" id="video-hook" ${spec.hook !== false ? 'checked' : ''}> Chữ hook đầu cảnh</label>
          <label style="display:flex;gap:8px;align-items:center;color:var(--text)"><input type="checkbox" id="video-bar" ${spec.progress_bar !== false ? 'checked' : ''}> Thanh tiến trình</label>
        </div>

        <label style="margin-top:10px">Nhạc nền (đường dẫn trong thư mục truyện)</label>
        <input type="text" id="video-bgm" value="${esc(spec.bgm?.path || '')}" placeholder="assets/nhac.mp3">

        <label style="margin-top:10px">Chất lượng</label>
        <select id="video-quality">
          <option value="high">Cao (1080p)</option>
          <option value="draft">Nháp (720p, nhanh)</option>
        </select>

        <div style="margin-top:12px">
          <label>Tỉ lệ xuất</label>
          <div class="ratio-grid">${ratioHtml}</div>
        </div>

        <div style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px">
          <label>Nền & lớp phủ</label>
          <div class="row wrap">
            <select id="video-bg-mode" style="width:auto">
              ${[['video', 'Video nền'], ['image', 'Ảnh AI'], ['gradient', 'Gradient']].map(([v, l]) =>
                `<option value="${v}" ${(bgSpec.mode || 'image') === v ? 'selected' : ''}>${l}</option>`).join('')}
            </select>
            <select id="video-bg-source" style="width:auto">
              <option value="random" ${bgSpec.source !== 'fixed' ? 'selected' : ''}>Ngẫu nhiên</option>
              <option value="fixed" ${bgSpec.source === 'fixed' ? 'selected' : ''}>Cố định</option>
            </select>
          </div>
          <select id="video-bg-file" style="margin-top:6px">${bgOptionsHtml(bgSpec.file)}</select>
          <div class="row" style="margin-top:8px">
            <input type="range" id="video-overlay" min="0" max="0.9" step="0.05" value="${overlay.opacity ?? 0.5}">
            <input type="color" id="video-overlay-color" value="${overlay.color || '#000000'}" style="width:46px;height:32px;padding:2px">
            <span class="hint" id="video-overlay-label">${Math.round((overlay.opacity ?? 0.5) * 100)}%</span>
          </div>
          <label style="margin-top:8px">Vị trí phụ đề</label>
          <select id="video-caption-pos">
            ${[['tiktok', 'TikTok / Reels'], ['youtube', 'YouTube (lower-third)'], ['center', 'Giữa khung'], ['upper', 'Phía trên']].map(([v, l]) =>
              `<option value="${v}" ${((spec.caption || {}).position || 'tiktok') === v ? 'selected' : ''}>${l}</option>`).join('')}
          </select>
        </div>

        <div style="margin-top:14px;border-top:1px solid var(--line);padding-top:12px">
          <label>Ảnh nền — ElevenLabs Image</label>
          <div class="row wrap">
            <select id="image-model" style="width:auto;min-width:210px">
              ${imageModels.map(m => `<option value="${m}" ${m === imageModel ? 'selected' : ''}>${m}</option>`).join('')}
            </select>
            <button class="small" data-act="gen-images" ${noScenes ? 'disabled' : ''}>Tạo ảnh cho cảnh trống</button>
            <button class="small ghost" data-act="gen-images-all" ${noScenes ? 'disabled' : ''}>Tạo lại tất cả</button>
          </div>
          <p class="hint" style="margin-top:8px">
            ${withArt}/${vscenes.length} cảnh đã có ảnh.
            ${app.state.config.eleven_ready
              ? 'Ảnh chạy qua ElevenLabs Image (cần gói Pro); nếu bị chặn sẽ tự chuyển sang Pollinations miễn phí.'
              : 'Chưa có key ElevenLabs — ảnh sẽ tạo bằng Pollinations (miễn phí) hoặc dùng nền gradient.'}
          </p>
        </div>

        <div class="row" style="margin-top:14px">
          <button class="primary grow" data-act="render-full" ${noScenes ? 'disabled' : ''}>Lồng tiếng + Dựng</button>
          <button data-act="render-only" ${noScenes ? 'disabled' : ''}>Dựng</button>
        </div>
        <p class="hint" style="margin-top:8px">
          ${voiced < vscenes.length
            ? `⚠ ${vscenes.length - voiced} cảnh chưa có tiếng — bấm <b>Lồng tiếng + Dựng</b> để làm cả hai trong một lần.`
            : 'Dựng tuần tự từng tỉ lệ để máy không bị quá tải. Có thể tiếp tục làm việc khác trong lúc chờ.'}
        </p>
      </div>

      <div class="card">
        <div class="row">
          <h3 style="margin:0">Video đã xuất</h3>
          <span class="grow"></span>
          <span class="chip">${renders.filter(r => r.status === 'done').length} bản</span>
        </div>
        <div class="render-grid" style="margin-top:12px">
          ${renderHtml || '<div class="empty">Chưa có video. Bấm “Lồng tiếng + Dựng”.</div>'}
        </div>
      </div>
    </div>`;
}

/* ----------------------------- insights ----------------------------- */
function viewInsights() {
  const runs = app.project.runs || [];
  return `
    <div class="card">
      <h3>Nhật ký AI (audit)</h3>
      <p class="hint">Mỗi lần model được gọi đều ghi lại: công cụ, cấp, model, token. Không có bước nào tự chạy ngầm.</p>
      <table style="width:100%;border-collapse:collapse;margin-top:10px;font-size:12px">
        <thead><tr style="color:var(--muted);text-align:left">
          <th style="padding:6px">Thời gian</th><th>Công cụ</th><th>Cấp</th><th>Model</th><th>Token</th><th>ms</th>
        </tr></thead>
        <tbody>
          ${runs.map(r => `<tr style="border-top:1px solid var(--line)">
            <td style="padding:6px" class="mono">${esc(r.created_at)}</td>
            <td>${esc(r.tool)}</td><td>${r.level}</td>
            <td class="mono">${esc(r.model || '')}</td>
            <td class="mono">${r.prompt_tokens}+${r.completion_tokens}</td>
            <td class="mono">${r.ms}</td>
          </tr>`).join('') || '<tr><td colspan="6" class="hint" style="padding:14px">Chưa gọi AI lần nào.</td></tr>'}
        </tbody>
      </table>
    </div>`;
}

/* ----------------------------- editors ----------------------------- */
function bindEditors() {
  document.querySelectorAll('[data-editor]').forEach(node => {
    const kind = node.dataset.editor;
    const id = node.dataset.id;
    node.addEventListener('change', async () => {
      try {
        if (kind === 'beat') {
          await api(`/api/beats/${id}`, { method: 'PATCH', body: { prose: node.value } });
          return;
        }
        const body = { [kind]: node.value };
        await api(`/api/scenes/${id}`, { method: 'PATCH', body });
        if (kind === 'narration' || kind === 'art') toast('Đã lưu — cần lồng tiếng lại cảnh này');
      } catch (err) { toast(err.message, true); }
    });
  });

  const ratioInputs = document.querySelectorAll('[data-ratio]');
  ratioInputs.forEach(input => {
    input.addEventListener('change', () => {
      if (input.checked) app.ratios.add(input.dataset.ratio); else app.ratios.delete(input.dataset.ratio);
      input.closest('.ratio-opt').classList.toggle('on', input.checked);
    });
  });

  const bindSave = (sel, fn) => { const node = q(sel); if (node) node.addEventListener('change', fn); };
  bindSave('#video-voice', e => { app.pendingVoice = e.target.value; saveSpec({ voice_profile: e.target.value }); });
  bindSave('#voice-select', e => { app.pendingVoice = e.target.value; saveSpec({ voice_profile: e.target.value }); });
  bindSave('#video-caption', e => saveSpec({ caption: { ...(currentVideo()?.spec?.caption || {}), name: e.target.value } }));
  bindSave('#video-watermark', e => saveSpec({ watermark: e.target.value }));
  bindSave('#video-hook', e => saveSpec({ hook: e.target.checked }));
  bindSave('#video-bar', e => saveSpec({ progress_bar: e.target.checked }));
  bindSave('#video-bgm', e => saveSpec({ bgm: { path: e.target.value, gain: 0.14 } }));

  const currentBg = () => ({ ...(currentVideo()?.spec?.background || {}) });
  const currentCaption = () => ({ ...(currentVideo()?.spec?.caption || {}) });
  bindSave('#video-bg-mode', e => saveSpec({ background: { ...currentBg(), mode: e.target.value } }));
  bindSave('#video-bg-source', e => saveSpec({ background: { ...currentBg(), source: e.target.value } }));
  bindSave('#video-bg-file', e => saveSpec({ background: { ...currentBg(), source: 'fixed', file: e.target.value } }));
  bindSave('#video-caption-pos', e => saveSpec({ caption: { ...currentCaption(), position: e.target.value } }));
  const overlayInput = q('#video-overlay');
  if (overlayInput) {
    overlayInput.oninput = (e) => {
      const label = q('#video-overlay-label');
      if (label) label.textContent = Math.round(e.target.value * 100) + '%';
    };
  }
  const saveOverlay = () => saveSpec({
    overlay: {
      color: q('#video-overlay-color')?.value || '#000000',
      opacity: Number(q('#video-overlay')?.value || 0),
    },
  });
  if (overlayInput) overlayInput.addEventListener('change', saveOverlay);
  bindSave('#video-overlay-color', saveOverlay);

  const picker = q('#video-picker');
  if (picker) {
    picker.onchange = (e) => { app.videoId = e.target.value; render(); };
  }
}

async function saveSpec(patch) {
  const video = currentVideo();
  if (!video) { toast('Chưa có bản dựng — hãy chuyển thể kịch bản trước', true); return; }
  try {
    await api(`/api/videos/${video.id}`, { method: 'PATCH', body: { spec: patch } });
    video.spec = { ...video.spec, ...patch };
  } catch (err) { toast(err.message, true); }
}

/* ----------------------------- actions ----------------------------- */
const actions = {
  async 'new-project'() {
    const dlg = document.getElementById('dlg-project');
    dlg.showModal();
    q('#form-project').onsubmit = async (ev) => {
      const submitter = ev.submitter;
      if (!submitter || submitter.value !== 'create') return;
      ev.preventDefault();
      const form = new FormData(ev.target);
      try {
        const { project } = await api('/api/projects', {
          method: 'POST',
          body: {
            title: form.get('title'), genre: form.get('genre'),
            idea: form.get('idea'), level: Number(form.get('level')),
          },
        });
        dlg.close();
        app.state = await api('/api/state');
        renderSidebar();
        await openProject(project.id);
        toast('Đã tạo truyện');
      } catch (err) { toast(err.message, true); }
    };
  },

  async 'open-project'(el) { await openProject(el.dataset.id); },
  async tab(el) { app.tab = el.dataset.id; renderTabs(); render(); },
  'toggle-chapter'(el) {
    const id = el.dataset.id;
    if (app.openChapters.has(id)) app.openChapters.delete(id); else app.openChapters.add(id);
    el.closest('.chapter').classList.toggle('open');
  },

  async 'ai-premise'() { await runAi('premise', 'Đang dựng ý tưởng…'); },
  async 'ai-bible'() { await runAi('bible', 'Đang dựng kinh thánh…'); },
  async 'ai-outline'() { await runAi('outline', 'Đang lập dàn ý…'); },
  async 'gen-beats'(el) { await runPost(`/api/chapters/${el.dataset.id}/beats`, 'Đang chia beat…'); },
  async 'write-beat'(el) {
    app.lastBeatId = el.dataset.id;
    await runPost(`/api/beats/${el.dataset.id}/write`, 'Đang viết…');
  },
  async 'polish-beat'(el) {
    const beat = findBeat(el.dataset.id);
    if (!beat || !beat.prose) return;
    await runBusy('Đang mài câu…', async () => {
      const { text } = await api(`/api/beats/${beat.id}/polish`, { method: 'POST', body: {} });
      await api(`/api/beats/${beat.id}`, { method: 'PATCH', body: { prose: text } });
      await openProject(app.project.project.id);
    });
  },

  async 'gen-script'() {
    const target = Number(q('#scenes-target')?.value || 8);
    const voice = q('#voice-select')?.value;
    const scope = q('#script-scope')?.value || '';
    const mode = q('#script-mode')?.value || 'verbatim';
    const split = (q('#script-split')?.value || '1') === '1';
    const syl = Number(q('#script-syllables')?.value || 32);
    const pasted = q('#script-source')?.value?.trim() || '';
    const pid = app.project.project.id;
    const label = mode === 'shorten'
      ? 'Đang rút gọn bằng AI…'
      : (split ? 'Đang chia cảnh (giữ nguyên văn)…' : 'Đang dựng một cảnh…');

    await runBusy(label, async () => {
      let created = 0;
      if (mode === 'verbatim') {
        let res;
        if (pasted) {
          res = await api(`/api/projects/${pid}/video-from-text`, {
            method: 'POST', body: { text: pasted, split, target_syllables: syl, voice_profile: voice },
          });
        } else if (scope) {
          res = await api(`/api/chapters/${scope}/video`, {
            method: 'POST', body: { mode: 'verbatim', split, target_syllables: syl, voice_profile: voice },
          });
        } else {
          const text = projectProse();
          if (!text) throw new Error('Truyện chưa có văn xuôi — viết beat trước hoặc dán văn bản.');
          res = await api(`/api/projects/${pid}/video-from-text`, {
            method: 'POST',
            body: { text, split, target_syllables: syl, voice_profile: voice, title: app.project.project.title },
          });
        }
        app.videoId = res.video.id;
        created = (res.scenes || []).length;
      } else {
        let video = currentVideo();
        if (!video) {
          const res = await api(`/api/projects/${pid}/videos`, {
            method: 'POST', body: { title: app.project.project.title, spec: { voice_profile: voice } },
          });
          video = res.video;
          app.videoId = video.id;
        }
        const res = await api(`/api/videos/${video.id}/script`, {
          method: 'POST',
          body: { scenes: target, source: pasted, voice_profile: voice, chapter_id: scope || undefined },
        });
        created = (res.scenes || []).length;
      }
      await openProject(pid);
      app.tab = 'script';
      renderTabs();
      render();
      toast(`${created} cảnh · ${mode === 'shorten' ? 'AI rút gọn' : 'giữ nguyên văn'}`);
    });
  },

  async 'open-autopilot'() {
    await populateAutopilot();
    document.getElementById('dlg-autopilot').showModal();
  },

  async 'run-autopilot'() {
    const pid = app.project.project.id;
    const source = q('#ap-source').value;
    const payload = {
      scope: source,
      chapter_id: source === 'chapter' ? q('#ap-chapter').value : '',
      source_text: source === 'text' ? q('#ap-text').value : '',
      title: source === 'text' ? app.project.project.title : '',
      target_seconds: Number(q('#ap-target').value),
      script_mode: q('#ap-mode').value,
      split: q('#ap-split').value === '1',
      target_syllables: Number(q('#ap-syllables').value || 32),
      background: {
        mode: q('#ap-bg').value,
        source: q('#ap-bg-source').value,
        file: q('#ap-bg-file').value,
      },
      overlay: { color: q('#ap-color').value, opacity: Number(q('#ap-opacity').value) },
      caption: { name: 'karaoke', position: q('#ap-pos').value },
      ratios: q('#ap-ratios').value.split(','),
      quality: q('#ap-quality').value,
      voice_profile: q('#ap-voice').value,
    };
    if (payload.scope === 'text' && !payload.source_text.trim()) {
      return toast('Chưa dán văn bản', true);
    }
    document.getElementById('dlg-autopilot').close();
    await startJob(`/api/projects/${pid}/autopilot`, payload);
  },


  async 'chapter-video'(el) {    const cid = el.dataset.id;
    const pid = app.project.project.id;
    const voice = app.pendingVoice || app.state.config.default_voice;
    await runBusy('Đang tạo video từ chương…', async () => {
      const res = await api(`/api/chapters/${cid}/video`, {
        method: 'POST', body: { scenes: Number(q('#scenes-target')?.value || 6), voice_profile: voice },
      });
      app.videoId = res.video.id;
      await openProject(pid);
      app.tab = 'video';
      renderTabs();
      render();
      toast(`Đã tạo bản dựng “${res.video.title}” với ${res.scenes.length} cảnh`);
    });
  },

  async 'new-video'() {
    const res = await api(`/api/projects/${app.project.project.id}/videos`, {
      method: 'POST',
      body: { title: `${app.project.project.title} (bản ${(app.project.videos || []).length + 1})` },
    });
    app.videoId = res.video.id;
    await openProject(app.project.project.id);
    toast('Đã tạo bản dựng mới — vào tab Kịch bản để tạo cảnh');
  },

  async 'add-scene'() {
    const video = currentVideo();
    await api(`/api/projects/${app.project.project.id}/scenes`, {
      method: 'POST',
      body: { narration: '', title: 'Cảnh mới', video_id: video?.id },
    });
    await openProject(app.project.project.id);
  },

  async 'del-scene'(el) {
    if (!confirm('Xoá cảnh này?')) return;
    await api(`/api/scenes/${el.dataset.id}`, { method: 'DELETE' });
    await openProject(app.project.project.id);
  },

  async 'voice-all'() {
    const video = currentVideo();
    if (!video) return toast('Chưa có bản dựng', true);
    const voice = q('#voice-select')?.value;
    await startJob(`/api/videos/${video.id}/voice`, { voice_profile: voice });
  },

  async 'render-full'() {
    const video = await ensureVideo();
    if (!video) return;
    const voice = q('#video-voice')?.value;
    await startJob(`/api/videos/${video.id}/full`, {
      ratios: [...app.ratios], voice_profile: voice, quality: q('#video-quality')?.value || 'high',
    });
  },

  async 'render-only'() {
    const video = await ensureVideo();
    if (!video) return;
    await startJob(`/api/videos/${video.id}/render`, {
      ratios: [...app.ratios], quality: q('#video-quality')?.value || 'high',
    });
  },

  async 'gen-images'() {
    const video = await ensureVideo();
    if (!video) return;
    await startJob(`/api/videos/${video.id}/images`, { model: q('#image-model')?.value });
  },

  async 'gen-images-all'() {
    const video = await ensureVideo();
    if (!video) return;
    if (!confirm('Tạo lại ảnh cho TẤT CẢ cảnh? Mỗi ảnh tốn credit ElevenLabs.')) return;
    await startJob(`/api/videos/${video.id}/images`, {
      model: q('#image-model')?.value, force: true,
    });
  },

  async 'scene-image'(el) {
    await runBusy('Đang tạo ảnh (ElevenLabs)…', async () => {
      await api(`/api/scenes/${el.dataset.id}/image`, {
        method: 'POST', body: { model: q('#image-model')?.value, force: true },
      });
      await openProject(app.project.project.id);
    });
  },

  async 'run-pipeline'() {
    const id = app.project.project.id;
    if (!confirm('Chạy toàn bộ pipeline (ý tưởng → kinh thánh → dàn ý → beat → kịch bản → video)? Việc này gọi AI nhiều lần và tốn token.')) return;
    await startJob(`/api/projects/${id}/pipeline`, { chapters: 3, beats: 2, scenes: 8, ratios: [...app.ratios] });
  },

  async 'open-settings'() {
    const { config } = await api('/api/settings');
    app.settings = config;
    renderSettings(config);
    document.getElementById('dlg-settings').showModal();
  },
  'close-settings'() { document.getElementById('dlg-settings').close(); },
  async 'save-settings'() {
    const cfg = collectSettings();
    await api('/api/settings', { method: 'POST', body: { config: cfg } });
    app.state = await api('/api/state');
    renderSystemInfo();
    document.getElementById('dlg-settings').close();
    toast('Đã lưu cài đặt');
  },
  async 'test-llm'() {
    const provider = q('#set-llm-provider')?.value;
    toast('Đang kiểm tra…');
    const res = await api('/api/settings/test-llm', { method: 'POST', body: { provider } });
    toast(res.message, !res.ok);
  },
  async 'test-eleven'() {
    toast('Đang kiểm tra ElevenLabs…');
    const res = await api('/api/settings/test-eleven', { method: 'POST', body: {} });
    toast(res.message, !res.ok);
  },
  'close-job'() { document.getElementById('jobbar').classList.remove('show'); },
};

function findBeat(id) {
  for (const ch of app.project.chapters) for (const b of ch.beats || []) if (b.id === id) return b;
  return null;
}

async function ensureVideo() {
  const video = currentVideo();
  if (video) return video;
  const voice = app.pendingVoice || q('#video-voice')?.value;
  const res = await api(`/api/projects/${app.project.project.id}/videos`, {
    method: 'POST', body: { title: app.project.project.title, spec: { voice_profile: voice } },
  });
  app.videoId = res.video.id;
  await openProject(app.project.project.id);
  return res.video;
}

async function runAi(path, label) {
  await runBusy(label, async () => {
    await api(`/api/projects/${app.project.project.id}/ai/${path}`, { method: 'POST', body: {} });
    await openProject(app.project.project.id);
  });
}

/** Gọi một endpoint AI cấp chương/beat (đường dẫn tuyệt đối). */
async function runPost(url, label) {
  await runBusy(label, async () => {
    await api(url, { method: 'POST', body: {} });
    await openProject(app.project.project.id);
  });
}

async function runBusy(label, fn) {
  const bar = document.getElementById('jobbar');
  bar.classList.add('show');
  document.getElementById('job-label').textContent = label;
  document.getElementById('job-fill').style.width = '55%';
  document.getElementById('job-pct').textContent = '…';
  try {
    await fn();
    document.getElementById('job-fill').style.width = '100%';
    toast('Xong');
  } catch (err) {
    toast(err.message, true);
  } finally {
    setTimeout(() => { bar.classList.remove('show'); document.getElementById('job-fill').style.width = '0'; }, 900);
  }
}

/* ----------------------------- jobs ----------------------------- */
async function startJob(url, body) {
  try {
    const { job } = await api(url, { method: 'POST', body });
    app.lastJob = job.id;
    document.getElementById('jobbar').classList.add('show');
    document.getElementById('job-label').textContent = 'Đang xếp hàng…';
    document.getElementById('job-fill').style.width = '2%';
    pollJobs(true);
  } catch (err) { toast(err.message, true); }
}

async function pollJobs(force) {
  clearTimeout(app.jobTimer);
  let active = null;
  try {
    const { jobs } = await api('/api/jobs');
    const running = jobs.find(j => j.status === 'running');
    const queued = jobs.find(j => j.status === 'queued');
    active = running || queued;
    if (app.lastJob) {
      const job = jobs.find(j => j.id === app.lastJob);
      if (job) {
        const bar = document.getElementById('jobbar');
        bar.classList.add('show');
        document.getElementById('job-label').textContent = job.message || job.kind;
        document.getElementById('job-fill').style.width = (job.progress || 0) + '%';
        document.getElementById('job-pct').textContent = (job.progress || 0) + '%';
        if (job.status === 'done') {
          toast('Job xong: ' + (job.message || job.kind));
          app.lastJob = null;
          setTimeout(() => bar.classList.remove('show'), 1500);
          app.state = await api('/api/state');
          if (app.project) await openProject(app.project.project.id);
        } else if (job.status === 'error') {
          toast('Lỗi: ' + (job.message || 'không rõ'), true);
          app.lastJob = null;
          if (app.project) await openProject(app.project.project.id);
        }
      }
    }
  } catch (err) { /* server đang bận */ }
  const delay = active ? 1800 : 5000;
  app.jobTimer = setTimeout(() => pollJobs(false), delay);
}

/* ----------------------------- settings ----------------------------- */
function renderSettings(cfg) {
  const llm = cfg.llm.providers;
  const current = cfg.llm.default;
  const p = llm[current] || {};
  const warnings = (cfg._warnings || []).map(w => `<p class="hint" style="color:#ffcf70">⚠ ${esc(w)}</p>`).join('');
  document.getElementById('settings-body').innerHTML = `
    ${warnings}
    <div>
      <label>Nhà cung cấp LLM</label>
      <select id="set-llm-provider">
        ${Object.entries(llm).map(([k, v]) => `<option value="${k}" ${k === current ? 'selected' : ''}>${esc(v.label || k)}</option>`).join('')}
      </select>
    </div>
    <div class="form-grid">
      <div><label>Base URL</label><input type="text" id="set-llm-base" value="${esc(p.base_url || '')}"></div>
      <div><label>Model</label><input type="text" id="set-llm-model" value="${esc(p.model || '')}"></div>
      <div class="full"><label>API key</label><input type="password" id="set-llm-key" value="${p.api_key === '***' ? '' : esc(p.api_key || '')}" placeholder="${p.api_key === '***' ? '•••• (đã lưu)' : 'sk-…'}"></div>
    </div>
    <p class="hint">DeepSeek dùng đúng endpoint mà DSH gọi (<span class="mono">api.deepseek.com/anthropic</span>, wire Messages). Key lấy tại
      <span class="mono">platform.deepseek.com/api_keys</span>. Token đăng nhập trong <span class="mono">~/.dsh</span> là token phiên — DeepSeek API công khai trả 401, nên cần key riêng.</p>

    <div class="sec-title"><h2>Giọng đọc & ảnh</h2><div class="line"></div></div>
    <div class="form-grid">
      <div><label>ElevenLabs key (giọng nam trầm + tạo ảnh)</label><input type="password" id="set-eleven-key" value="${cfg.tts.providers.elevenlabs.api_key === '***' ? '' : (cfg.tts.providers.elevenlabs.api_key || '')}" placeholder="${cfg.tts.providers.elevenlabs.api_key === '***' ? '•••• (đã lưu)' : 'xi-…'}"></div>
      <div><label>FPT.AI key (dự phòng giọng Việt)</label><input type="password" id="set-fpt-key" value="${cfg.tts.providers.fpt.api_key === '***' ? '' : (cfg.tts.providers.fpt.api_key || '')}"></div>
      <div><label>Azure Speech key</label><input type="password" id="set-azure-key" value="${cfg.tts.providers.azure.api_key === '***' ? '' : (cfg.tts.providers.azure.api_key || '')}"></div>
      <div><label>Azure region</label><input type="text" id="set-azure-region" value="${esc(cfg.tts.providers.azure.region || 'southeastasia')}"></div>
    </div>
    <p class="hint">Mặc định: ElevenLabs · giọng Sang Trương (nam trầm) + ảnh <span class="mono">${esc(cfg.images?.model || '')}</span>.
      Chưa có key ElevenLabs thì giọng tự rơi về Edge Nam Minh và video dùng nền gradient.</p>
  `;
  const providerSelect = q('#set-llm-provider');
  if (providerSelect) {
    providerSelect.onchange = (e) => {
      const prov = app.settings.llm.providers[e.target.value] || {};
      q('#set-llm-base').value = prov.base_url || '';
      q('#set-llm-model').value = prov.model || '';
      q('#set-llm-key').value = '';
      q('#set-llm-key').placeholder = prov.api_key === '***' ? '•••• (đã lưu)' : 'sk-…';
    };
  }
}

function collectSettings() {
  const provider = q('#set-llm-provider').value;
  const key = q('#set-llm-key').value.trim();
  const llmPatch = {
    base_url: q('#set-llm-base').value.trim(),
    model: q('#set-llm-model').value.trim(),
  };
  if (key && key !== '***') llmPatch.api_key = key;
  const ttsPatch = {
    azure: { region: q('#set-azure-region').value.trim() || 'southeastasia' },
    fpt: {}, elevenlabs: {}, openai: {},
  };
  const fptKey = q('#set-fpt-key').value.trim();
  const azureKey = q('#set-azure-key').value.trim();
  const elevenKey = q('#set-eleven-key').value.trim();
  if (fptKey && fptKey !== '***') ttsPatch.fpt.api_key = fptKey;
  if (azureKey && azureKey !== '***') ttsPatch.azure.api_key = azureKey;
  if (elevenKey && elevenKey !== '***') {
    ttsPatch.elevenlabs.api_key = elevenKey;
  }
  const patch = {
    llm: { default: provider, providers: { [provider]: llmPatch } },
    tts: { providers: ttsPatch },
  };
  if (elevenKey && elevenKey !== '***') {
    patch.tts.default_profile = 'nam-tram-eleven';
    patch.images = { providers: { elevenlabs: { api_key: elevenKey } } };
  }
  return patch;
}

/* ----------------------------- events ----------------------------- */
document.addEventListener('click', async (ev) => {
  const target = ev.target.closest('[data-act]');
  if (!target) return;
  const fn = actions[target.dataset.act];
  if (!fn) return;
  ev.preventDefault();
  try { await fn(target); } catch (err) { toast(err.message, true); }
});

boot();
