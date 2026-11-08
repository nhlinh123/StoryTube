/**
 * Smoke test giao diện: chạy app.js trong Node với DOM giả + API giả.
 * Mục đích: bắt lỗi runtime (biến không tồn tại, render nổ) mà không cần trình duyệt.
 *
 *   node tools/ui_smoke.js
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const code = fs.readFileSync(path.join(root, 'storytube/web/app.js'), 'utf8');

function makeEl(id = '') {
  const el = {
    id,
    innerHTML: '',
    textContent: '',
    value: '',
    style: {},
    dataset: {},
    children: [],
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      toggle(c, force) { (force === undefined ? !this._set.has(c) : force) ? this._set.add(c) : this._set.delete(c); },
      contains(c) { return this._set.has(c); },
    },
    appendChild(child) { this.children.push(child); return child; },
    addEventListener() {},
    removeEventListener() {},
    querySelector() { return makeEl(); },
    querySelectorAll() { return []; },
    closest() { return null; },
    showModal() {},
    close() {},
    remove() {},
    focus() {},
  };
  return el;
}

const elements = new Map();
function byId(id) {
  if (!elements.has(id)) elements.set(id, makeEl(id));
  return elements.get(id);
}

const document = {
  getElementById: byId,
  querySelector: (sel) => (sel.startsWith('#') ? byId(sel.slice(1)) : makeEl(sel)),
  querySelectorAll: () => [],
  createElement: () => makeEl(),
  addEventListener() {},
  body: makeEl('body'),
};

const project = {
  project: {
    id: 'prj_1', title: 'Người giữ đèn biển', slug: 'nguoi-giu-den-bien',
    genre: 'tâm lý', logline: 'Một người giữ hải đăng.', style: 'lạnh', level: 4,
    meta: JSON.stringify({ premise: { hook_line: 'Đêm thứ ba', logline: 'Một người giữ hải đăng.' } }),
  },
  entities: [
    { id: 'e1', kind: 'character', name: 'Ông Bảy', summary: 'Người giữ đèn', details: '{}' },
    { id: 'e2', kind: 'location', name: 'Hải đăng', summary: 'Tháp đá', details: '{}' },
  ],
  chapters: [
    { id: 'c1', idx: 1, title: 'Người lên đèn', synopsis: 'Đêm mưa.', hook: 'Cô gái tên Linh.',
      beats: [{ id: 'b1', idx: 1, summary: 'Leo tháp', prose: 'Đêm thứ ba mưa không tắt.', words: 7, status: 'written' }] },
    { id: 'c2', idx: 2, title: 'Lá thư', synopsis: 'Ngăn kéo.', hook: '',
      beats: [{ id: 'b2', idx: 1, summary: 'Mở ngăn kéo', prose: '', words: 0, status: 'planned' }] },
  ],
  scenes: [
    { id: 's1', idx: 1, title: 'Mưa đêm', narration: 'Đêm thứ ba, mưa không tắt.', on_screen: 'Đêm thứ ba',
      visual_prompt: '', mood: 'lanh', art: '', duration_ms: 8000, status: 'voiced', words: [], audio_path: 'x' },
  ],
  videos: [{
    id: 'v1', title: 'Người giữ đèn biển', status: 'rendered', spec: {
      voice_profile: 'viet-google', caption: { name: 'karaoke' }, ratios: ['9:16'], hook: true, progress_bar: true,
    },
    renders: [{ id: 'r1', ratio: '9:16', status: 'done', url: '/media/a.mp4', thumb_url: '/media/a.jpg',
      bytes: 12345678, duration_ms: 80000, path: 'x' }],
    scene_count: 1, scene_ids: ['s1'],
  }],
  runs: [{ created_at: '2026-01-01T00:00:00', tool: 'script', level: 4, model: 'x', prompt_tokens: 10, completion_tokens: 5, ms: 900 }],
  stats: { words: 7, chapters: 1, scenes: 1, duration: 80000, duration_text: '1:20' },
};

const state = {
  projects: [{ id: 'prj_1', title: 'Người giữ đèn biển', genre: 'tâm lý', counts: { scenes: 1, renders: 1 } }],
  config: {
    level: 4, default_voice: 'nam-tram-am',
    voices: [{ name: 'nam-tram-am', label: 'Nam trầm ấm' }, { name: 'viet-google', label: 'Google' }],
    ratios: [{ key: '9:16', label: 'TikTok', w: 1080, h: 1920 }],
    llm_ready: true, ffmpeg: true, llm_default: 'openai',
  },
  jobs: [{ id: 'j1', kind: 'render', status: 'done', progress: 100, message: 'Xong' }],
  version: '0.1.0',
};

const settings = {
  config: {
    llm: { default: 'openai', providers: { openai: { label: 'OpenAI', base_url: 'https://api.openai.com/v1', model: 'gpt-4.1-mini', api_key: '***' } } },
    tts: { providers: { fpt: { api_key: '' }, azure: { api_key: '', region: 'southeastasia' }, elevenlabs: { api_key: '' } } },
  },
};

const fetch = async (url) => {
  const body =
    url === '/api/state' ? state
    : url.startsWith('/api/projects/') && url.split('/').length === 4 ? project
    : url === '/api/jobs' ? { jobs: state.jobs }
    : url === '/api/settings' ? settings
    : {};
  return { ok: true, status: 200, json: async () => body };
};

const sandbox = {
  document,
  window: { scrollY: 0, scrollTo() {} },
  fetch, console,
  requestAnimationFrame: (fn) => fn(),
  setTimeout: () => 0,
  clearTimeout: () => {},
  FormData: class { get() { return ''; } },
  confirm: () => true,
  alert: () => {},
};
sandbox.globalThis = sandbox;

(async () => {
  vm.createContext(sandbox);
  vm.runInContext(code + '\nglobalThis.__app = app; globalThis.__render = render; globalThis.__openProject = openProject;', sandbox);
  await new Promise((r) => setImmediate(r));
  await new Promise((r) => setImmediate(r));

  const app = sandbox.__app;
  const view = byId('view');
  const checks = [];
  const expect = (label, cond) => checks.push([label, !!cond]);

  expect('boot tải được state', app.state && app.state.projects.length === 1);
  expect('mở được project', app.project && app.project.project.id === 'prj_1');
  expect('sidebar có truyện', byId('project-list').innerHTML.includes('Người giữ đèn biển'));

  for (const tab of ['story', 'script', 'video', 'insights']) {
    app.tab = tab;
    sandbox.__render();
    expect(`tab ${tab} render ra HTML`, view.innerHTML.length > 100);
  }

  app.tab = 'story';
  sandbox.__render();
  expect('story có kinh thánh', view.innerHTML.includes('Kinh thánh'));
  expect('story có beat', view.innerHTML.includes('Đêm thứ ba mưa không tắt'));

  // mở 2 chương rồi refresh: không được collapse về chương đầu
  app.openChapters = new Set(['c1', 'c2']);
  await sandbox.__openProject('prj_1');
  expect('refresh giữ nguyên chương đang mở', app.openChapters.size === 2);

  app.openChapters = new Set(['c2']);
  await sandbox.__openProject('prj_1');
  expect('refresh giữ đúng chương đang làm việc', app.openChapters.has('c2') && !app.openChapters.has('c1'));

  app.tab = 'script';
  sandbox.__render();
  expect('script có lời đọc', view.innerHTML.includes('Đêm thứ ba, mưa không tắt.'));
  expect('script có lựa chọn giọng', view.innerHTML.includes('Nam trầm ấm'));

  app.analysis = {
    target_seconds: 90,
    totals: { read_text: '19:52', words: 4791 },
    scope: { suggested_scenes: 12 },
    plans: { condensed: { episodes: 6, scenes_per_episode: 12 }, full: { episodes: 16, scenes_per_episode: 12 } },
    message: 'Toàn truyện đọc hết khoảng 19:52',
    per_chapter: [{ idx: 1, title: 'Người lên đèn', words: 673, read_seconds: 169, episodes: 2, scenes_per_episode: 12, scene_count: 0 }],
  };
  sandbox.__render();
  expect('có bảng phân tích', view.innerHTML.includes('Phân tích truyện') && view.innerHTML.includes('Dùng 12 cảnh'));
  app.analysis = null;

  app.tab = 'video';
  sandbox.__render();
  expect('video có tỉ lệ', view.innerHTML.includes('9:16'));
  expect('video có link tải', view.innerHTML.includes('/media/a.mp4'));

  app.tab = 'insights';
  sandbox.__render();
  expect('insights có log', view.innerHTML.includes('script'));

  let failed = 0;
  for (const [label, pass] of checks) {
    console.log(`${pass ? 'OK  ' : 'FAIL'}  ${label}`);
    if (!pass) failed += 1;
  }
  console.log(failed ? `\n${failed} kiểm tra thất bại` : `\nTất cả ${checks.length} kiểm tra giao diện đều đạt`);
  process.exit(failed ? 1 : 0);
})().catch((err) => {
  console.error('SMOKE ERROR:', err);
  process.exit(1);
});
