const connection = document.getElementById('connection');
const connect = document.getElementById('connect');
const toggle = document.getElementById('toggle');
const picture = document.getElementById('preview');
const viewer = picture.closest('.viewer');
const placeholder = document.getElementById('placeholder');
const previewMessage = document.getElementById('previewMessage');
const videoState = document.getElementById('videoState');
const route = document.getElementById('route');
const boardHost = document.getElementById('boardHost');
const hotspotSsid = document.getElementById('hotspotSsid');
const resolution = document.getElementById('resolution');
const fpsSelect = document.getElementById('fps');
const profile = document.getElementById('profile');

const FPS_CHOICES = {
  '640x480': [25, 20, 15, 10, 5],
  '800x600': [30, 25, 20, 15, 10, 5],
  '1024x768': [25, 20, 15, 10, 5],
  '1280x960': [25, 20, 15, 10, 5],
  '1920x1440': [12, 10, 5],
};
const connectionMessage = document.getElementById('connectionMessage');

let paused = false;
let ready = false;
let connecting = false;
let retryAfter = 0;
let requestId = 0;
let hadReady = false;
let nextAutoRetry = 0;
let settingBusy = false;

function fillFps(keep) {
  const choices = FPS_CHOICES[resolution.value] || [15];
  fpsSelect.innerHTML = choices.map((v) => `<option value="${v}">${v} 帧/秒</option>`).join('');
  if (choices.map(String).includes(String(keep))) fpsSelect.value = String(keep);
}

function profileText() {
  const [w, h] = resolution.value.split('x');
  return `${w} × ${h} · ${fpsSelect.value} 帧/秒`;
}

fillFps(15);
profile.textContent = profileText();

function removePicture() {
  picture.removeAttribute('src');
  picture.hidden = true;
  placeholder.hidden = false;
}

function updatePicture() {
  viewer.classList.toggle('connection-controls-first', !ready);
  toggle.disabled = !ready;
  toggle.textContent = paused ? '继续预览' : '暂停预览';
  if (!ready || paused) {
    removePicture();
    videoState.textContent = paused && ready ? '已暂停' : '等待连接';
    previewMessage.textContent = paused && ready ? '实时预览已暂停' : '连接香橙派后显示画面';
  } else if (!picture.hasAttribute('src') && Date.now() >= retryAfter) {
    videoState.textContent = '正在加载';
    previewMessage.textContent = '正在接收摄像头画面…';
    picture.src = `/live.mjpg?view=${++requestId}`;
  }
}

async function updateStatus() {
  try {
    const response = await fetch('/api/status', { cache: 'no-store', signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw new Error('Status request failed');
    const status = await response.json();
    ready = status.ready;
    connecting = status.connecting;
    connection.dataset.state = connecting ? 'busy' : ready ? 'online' : 'idle';
    const routeLabel = status.route === 'tailscale' ? 'Tailscale'
      : status.route === 'hotspot' ? 'USB 热点' : null;
    connection.textContent = connecting ? '正在连接' : routeLabel ? `${routeLabel} 已连接` : '未连接';
    route.textContent = routeLabel || '—';
    boardHost.textContent = status.board_host || '—';
    hotspotSsid.textContent = status.hotspot_ssid || '—';
    if (status.resolution && status.fps && !settingBusy) {
      if (resolution.value !== status.resolution) {
        resolution.value = status.resolution;
        fillFps(status.fps);
      }
      fpsSelect.value = String(status.fps);
    }
    if (status.resolution && status.fps) {
      const [w, h] = status.resolution.split('x');
      profile.textContent = `${w} × ${h} · ${status.fps} 帧/秒`;
    }
    connectionMessage.textContent = status.message;
    if (ready) {
      hadReady = true;
      nextAutoRetry = 0;
    } else if (hadReady && !connecting && Date.now() >= nextAutoRetry) {
      nextAutoRetry = Date.now() + 20000;
      fetch('/api/refresh', {
        method: 'POST', headers: { 'X-OrangePi-Console': 'connect' },
      }).catch(() => {});
    }
    if (ready && status.streaming && !paused && picture.hasAttribute('src')) {
      picture.hidden = false;
      placeholder.hidden = true;
      videoState.textContent = '直播中';
    }
  } catch {
    ready = false;
    connecting = false;
    connection.dataset.state = 'idle';
    connection.textContent = '本地服务已停止';
    route.textContent = '—';
    connectionMessage.textContent = '请重新运行启动脚本。';
  }
  connect.disabled = connecting;
  connect.textContent = connecting ? '正在连接…' : ready ? '检查连接' : '连接香橙派';
  updatePicture();
}

picture.addEventListener('load', () => {
  if (!ready || paused || !picture.hasAttribute('src')) return;
  picture.hidden = false;
  placeholder.hidden = true;
  videoState.textContent = '直播中';
});

picture.addEventListener('error', () => {
  if (!ready || paused || !picture.hasAttribute('src')) return;
  removePicture();
  retryAfter = Date.now() + 3000;
  videoState.textContent = '重新加载中';
  previewMessage.textContent = '画面暂不可用。若已打开其他预览，请先关闭。';
});

toggle.addEventListener('click', () => {
  paused = !paused;
  retryAfter = 0;
  updatePicture();
});

async function applySettings() {
  settingBusy = true;
  paused = false;
  retryAfter = 0;
  removePicture();
  try {
    await fetch(`/api/connect?resolution=${resolution.value}&fps=${fpsSelect.value}&restart=1&mode=tailscale`,
      { method: 'POST', headers: { 'X-OrangePi-Console': 'connect' } });
    await updateStatus();
  } catch {
    connectionMessage.textContent = '参数切换失败，请重新运行启动脚本。';
  } finally {
    settingBusy = false;
  }
}

resolution.addEventListener('change', () => {
  fillFps();
  profile.textContent = profileText();
  applySettings();
});

fpsSelect.addEventListener('change', () => {
  profile.textContent = profileText();
  applySettings();
});

connect.addEventListener('click', async () => {
  connect.disabled = true;
  paused = false;
  retryAfter = 0;
  try {
    const response = await fetch('/api/connect', { method: 'POST', headers: { 'X-OrangePi-Console': 'connect' } });
    if (!response.ok) throw new Error('Connect request failed');
    await updateStatus();
  } catch {
    connectionMessage.textContent = '无法启动连接，请重新运行启动脚本。';
    connect.disabled = false;
  }
});

async function poll() {
  await updateStatus();
  setTimeout(poll, 1800);
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
const tabCamera = document.getElementById('tab-camera');
const tabLogs = document.getElementById('tab-logs');
const tabMsp = document.getElementById('tab-msp');
const panelCamera = document.getElementById('panel-camera');
const panelLogs = document.getElementById('panel-logs');
const panelMsp = document.getElementById('panel-msp');

function selectTab(name) {
  const logs = name === 'logs';
  const msp = name === 'msp';
  tabCamera.setAttribute('aria-selected', String(name === 'camera'));
  tabLogs.setAttribute('aria-selected', String(logs));
  tabMsp.setAttribute('aria-selected', String(msp));
  panelCamera.hidden = name !== 'camera';
  panelLogs.hidden = !logs;
  panelMsp.hidden = !msp;
  if (logs && autoScroll.checked) logWindow.scrollTop = logWindow.scrollHeight;
  history.replaceState(null, '', name === 'camera' ? location.pathname : `#${name}`);
  if (msp) refreshPorts();
}

tabCamera.addEventListener('click', () => selectTab('camera'));
tabLogs.addEventListener('click', () => selectTab('logs'));
tabMsp.addEventListener('click', () => selectTab('msp'));

// ---------------------------------------------------------------------------
// Live logs (Server-Sent Events)
// ---------------------------------------------------------------------------
const logSource = document.getElementById('logSource');
const customSource = document.getElementById('customSource');
const customType = document.getElementById('customType');
const customValue = document.getElementById('customValue');
const logStart = document.getElementById('logStart');
const logPause = document.getElementById('logPause');
const logClear = document.getElementById('logClear');
const autoScroll = document.getElementById('autoScroll');
const logFilter = document.getElementById('logFilter');
const logWindow = document.getElementById('logWindow');
const logEmpty = document.getElementById('logEmpty');
const logStatus = document.getElementById('logStatus');
const logMeta = document.getElementById('logMeta');
const logCount = document.getElementById('logCount');

const MAX_LINES = 3000;
const MAX_PENDING = 5000;

let eventSource = null;
let logPaused = false;
let lineNumber = 0;
let activeFilter = null;
let pending = [];
let pendingDropped = 0;

if (location.hash === '#logs') selectTab('logs');

logSource.addEventListener('change', () => {
  customSource.hidden = logSource.value !== 'custom';
  if (logSource.value === 'custom') customValue.focus();
});

function currentSource() {
  const value = logSource.value;
  if (value !== 'custom') return value;
  const raw = customValue.value.trim();
  if (!raw) throw new Error('请填写自定义来源');
  return `${customType.value}:${raw}`;
}

function levelOf(text) {
  if (/\b(error|err|fatal|crit|panic|emerg|alert|exception|failed|failure)\b/i.test(text)) return 'level-error';
  if (/\b(warn|warning|deprecated)\b/i.test(text)) return 'level-warn';
  if (/\b(info|notice)\b/i.test(text)) return 'level-info';
  return '';
}

function compileFilter() {
  const text = logFilter.value.trim();
  if (!text) return null;
  const regex = /^\/(.+)\/([a-z]*)$/.exec(text);
  try {
    return regex ? new RegExp(regex[1], regex[2])
      : new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'i');
  } catch {
    return null;
  }
}

function matchesFilter(text) {
  return !activeFilter || activeFilter.test(text);
}

function makeLine(text) {
  lineNumber += 1;
  const row = document.createElement('div');
  row.className = `log-line ${levelOf(text)}`;
  const num = document.createElement('span');
  num.className = 'num';
  num.textContent = String(lineNumber);
  const body = document.createElement('span');
  body.className = 'text';
  body.textContent = text;
  row.append(num, body);
  row.dataset.text = text;
  if (!matchesFilter(text)) row.hidden = true;
  return row;
}

function appendLines(texts) {
  if (!texts.length) return;
  logEmpty.hidden = true;
  const fragment = document.createDocumentFragment();
  texts.map(makeLine).forEach((row) => fragment.appendChild(row));
  logWindow.appendChild(fragment);
  const rows = logWindow.querySelectorAll('.log-line');
  const overflow = rows.length - MAX_LINES;
  if (overflow > 0) [...rows].slice(0, overflow).forEach((row) => row.remove());
  logCount.textContent = `${logWindow.querySelectorAll('.log-line').length} 行`;
  if (autoScroll.checked) logWindow.scrollTop = logWindow.scrollHeight;
}

function appendLine(text) {
  if (logPaused) {
    pending.push(text);
    if (pending.length > MAX_PENDING) {
      pending.shift();
      pendingDropped += 1;
    }
    logCount.textContent = `${logWindow.querySelectorAll('.log-line').length} 行 · 暂停 +${pending.length}`;
    return;
  }
  appendLines([text]);
}

function setLogStatus(state, text) {
  logStatus.dataset.state = state;
  logStatus.textContent = text;
}

function stopLog(keepStatus) {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
  logPause.disabled = true;
  logStart.disabled = false;
  if (!keepStatus) setLogStatus('idle', '未连接');
}

function startLog() {
  let source;
  try {
    source = currentSource();
  } catch (error) {
    setLogStatus('error', error.message);
    return;
  }
  stopLog(true);
  pending = [];
  pendingDropped = 0;
  logPaused = false;
  logPause.textContent = '暂停';
  logPause.disabled = false;
  logStart.disabled = true;
  setLogStatus('live', '连接中…');
  logMeta.textContent = source;

  const events = new EventSource(`/api/logs?source=${encodeURIComponent(source)}`);
  eventSource = events;

  events.addEventListener('meta', (message) => {
    try {
      logMeta.textContent = JSON.parse(message.data).command || source;
    } catch { /* keep source */ }
    setLogStatus('live', '实时读取中');
  });

  events.addEventListener('line', (message) => {
    try {
      appendLine(JSON.parse(message.data).line);
    } catch {
      appendLine(message.data);
    }
  });

  events.addEventListener('end', (message) => {
    let reason = '日志流已结束';
    try {
      reason = JSON.parse(message.data).reason || reason;
    } catch { /* default */ }
    stopLog(true);
    setLogStatus('error', reason);
  });

  events.addEventListener('error', () => {
    if (events.readyState === EventSource.CLOSED) {
      stopLog(true);
      setLogStatus('error', '日志连接已断开');
    } else {
      setLogStatus('live', '重新连接中…');
    }
  });
}

logStart.addEventListener('click', startLog);

logPause.addEventListener('click', () => {
  logPaused = !logPaused;
  logPause.textContent = logPaused ? '继续' : '暂停';
  if (!logPaused) {
    const buffered = pending;
    pending = [];
    if (pendingDropped) buffered.push(`… 暂停期间丢弃了 ${pendingDropped} 行 …`);
    pendingDropped = 0;
    appendLines(buffered);
    setLogStatus('live', '实时读取中');
  } else {
    setLogStatus('paused', '已暂停（继续接收，不滚动）');
  }
});

logClear.addEventListener('click', () => {
  logWindow.querySelectorAll('.log-line').forEach((row) => row.remove());
  lineNumber = 0;
  pending = [];
  pendingDropped = 0;
  logEmpty.hidden = false;
  logCount.textContent = '0 行';
});

let filterTimer = 0;
logFilter.addEventListener('input', () => {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => {
    activeFilter = compileFilter();
    logWindow.querySelectorAll('.log-line').forEach((row) => {
      row.hidden = !matchesFilter(row.dataset.text || '');
    });
    logCount.textContent = `${[...logWindow.querySelectorAll('.log-line')].filter((r) => !r.hidden).length} / ${logWindow.querySelectorAll('.log-line').length} 行`;
  }, 180);
});

// ---------------------------------------------------------------------------
// MSPM0G3507 flashing and serial monitor (chip attached to the Orange Pi)
// ---------------------------------------------------------------------------
const flashPort = document.getElementById('flashPort');
const monitorPort = document.getElementById('monitorPort');
const monitorBaud = document.getElementById('monitorBaud');
const flashBaud = document.getElementById('flashBaud');
const hexFile = document.getElementById('hexFile');
const flashStart = document.getElementById('flashStart');
const flashButton = document.getElementById('flashButton');
const flashProgress = document.getElementById('flashProgress');
const flashLog = document.getElementById('flashLog');
const monitorLog = document.getElementById('monitorLog');
const monitorConnect = document.getElementById('monitorConnect');
const monitorDisconnect = document.getElementById('monitorDisconnect');
const sendText = document.getElementById('sendText');
const sendMode = document.getElementById('sendMode');
const sendNewline = document.getElementById('sendNewline');
const sendButton = document.getElementById('sendButton');
const hexView = document.getElementById('hexView');
const monitorAutoScroll = document.getElementById('monitorAutoScroll');

const monDecoder = new TextDecoder('utf-8');
let serialSource = null;
let monBuffer = '';

function mspLog(box, text) {
  const el = box === 'monitorLog' ? monitorLog : flashLog;
  const row = document.createElement('div');
  row.className = `log-line ${levelOf(text)}`;
  const body = document.createElement('span');
  body.className = 'text';
  body.textContent = text;
  row.appendChild(body);
  el.appendChild(row);
  while (el.querySelectorAll('.log-line').length > 2000) el.firstElementChild.remove();
  if (box !== 'monitorLog' || monitorAutoScroll.checked) el.scrollTop = el.scrollHeight;
}

function fillPortSelect(select, ports) {
  const keep = select.value;
  select.textContent = '';
  if (!ports.length) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = '未发现串口';
    select.appendChild(option);
    return;
  }
  for (const item of ports) {
    const option = document.createElement('option');
    option.value = item.device;
    option.textContent = item.description ? `${item.device} · ${item.description}` : item.device;
    select.appendChild(option);
  }
  if (ports.some((item) => item.device === keep)) select.value = keep;
}

async function refreshPorts() {
  try {
    const response = await fetch('/api/mspm0/ports', { cache: 'no-store', signal: AbortSignal.timeout(8000) });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '读取串口失败');
    const ports = data.ports || [];
    fillPortSelect(flashPort, ports);
    fillPortSelect(monitorPort, ports);
    mspLog('flashLog', ports.length ? `发现 ${ports.length} 个串口` : '香橙派上没有发现串口，请检查 USB 连接');
  } catch (error) {
    mspLog('flashLog', `读取串口失败：${error.message}`);
  }
}

document.getElementById('refreshPorts').addEventListener('click', refreshPorts);

flashButton.addEventListener('click', async () => {
  const port = flashPort.value;
  const file = hexFile.files[0];
  if (!port) { mspLog('flashLog', '请选择串口'); return; }
  if (!file) { mspLog('flashLog', '请选择 .hex 固件文件'); return; }
  flashButton.disabled = true;
  flashProgress.value = 0;
  mspLog('flashLog', `读取固件 ${file.name}（${file.size} 字节）…`);
  try {
    const upload = await fetch('/api/mspm0/upload', {
      method: 'POST', headers: { 'X-OrangePi-Console': 'connect' }, body: file,
    });
    const uploaded = await upload.json();
    if (!upload.ok) throw new Error(uploaded.error || '固件上传失败');
    mspLog('flashLog', `固件已上传到香橙派（${uploaded.bytes} 字节），开始烧录…`);
    const url = `/api/mspm0/flash?port=${encodeURIComponent(port)}&baud=${flashBaud.value}&start=${flashStart.checked ? 1 : 0}`;
    const events = new EventSource(url);
    const finish = () => { events.close(); flashButton.disabled = false; };
    events.addEventListener('line', (message) => {
      let line;
      try { line = JSON.parse(message.data).line; } catch { line = message.data; }
      if (line.startsWith('PROGRESS ')) { flashProgress.value = Number(line.slice(9)) || 0; return; }
      if (line.startsWith('LOG ')) line = line.slice(4);
      if (line === 'DONE') { flashProgress.value = 100; mspLog('flashLog', '✓ 烧录完成'); finish(); return; }
      if (line.startsWith('FAIL ')) line = `✗ ${line.slice(5)}`;
      mspLog('flashLog', line);
    });
    events.addEventListener('end', finish);
    events.addEventListener('error', () => {
      if (events.readyState === EventSource.CLOSED) { mspLog('flashLog', '烧录连接已断开'); finish(); }
    });
  } catch (error) {
    mspLog('flashLog', `烧录失败：${error.message}`);
    flashButton.disabled = false;
  }
});

function detachSerial(closed) {
  if (serialSource) { serialSource.close(); serialSource = null; }
  monitorConnect.disabled = false;
  monitorDisconnect.disabled = true;
  sendButton.disabled = true;
  if (closed) mspLog('monitorLog', '串口已断开');
}

function renderSerial(hex) {
  if (!/^([0-9a-f]{2})*$/.test(hex)) return;
  const bytes = new Uint8Array(hex.match(/../g).map((pair) => parseInt(pair, 16)));
  if (hexView.checked) { mspLog('monitorLog', `HEX ${hex}`); return; }
  monBuffer += monDecoder.decode(bytes, { stream: true });
  let index;
  while ((index = monBuffer.indexOf('\n')) >= 0) {
    mspLog('monitorLog', monBuffer.slice(0, index).replace(/\r$/, ''));
    monBuffer = monBuffer.slice(index + 1);
  }
  if (monBuffer.length > 8192) { mspLog('monitorLog', monBuffer); monBuffer = ''; }
}

monitorConnect.addEventListener('click', async () => {
  const port = monitorPort.value;
  const baud = Number(monitorBaud.value);
  if (!port) { mspLog('monitorLog', '请选择串口'); return; }
  try {
    const response = await fetch(`/api/serial/start?port=${encodeURIComponent(port)}&baud=${baud}`,
      { method: 'POST', headers: { 'X-OrangePi-Console': 'connect' } });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '连接失败');
    monBuffer = '';
    monitorConnect.disabled = true;
    monitorDisconnect.disabled = false;
    sendButton.disabled = false;
    mspLog('monitorLog', `正在打开 ${port} @ ${baud}…`);
    serialSource = new EventSource('/api/serial/stream');
    serialSource.addEventListener('meta', (message) => {
      try {
        const meta = JSON.parse(message.data);
        mspLog('monitorLog', `已连接 ${meta.port} @ ${meta.baud}`);
      } catch { /* ignore */ }
    });
    serialSource.addEventListener('line', (message) => {
      let line;
      try { line = JSON.parse(message.data).line; } catch { line = message.data; }
      if (line.startsWith('DATA ')) { renderSerial(line.slice(5)); return; }
      if (line.startsWith('READY')) { mspLog('monitorLog', '串口已打开'); return; }
      if (line === 'CLOSED') { detachSerial(true); return; }
      if (line.startsWith('ERR ')) { mspLog('monitorLog', `✗ ${line.slice(4)}`); return; }
      mspLog('monitorLog', line);
    });
    serialSource.addEventListener('end', () => detachSerial(true));
    serialSource.addEventListener('error', () => {
      if (serialSource && serialSource.readyState === EventSource.CLOSED) detachSerial(true);
    });
  } catch (error) {
    mspLog('monitorLog', `连接失败：${error.message}`);
    monitorConnect.disabled = false;
  }
});

monitorDisconnect.addEventListener('click', async () => {
  try {
    await fetch('/api/serial/stop', { method: 'POST', headers: { 'X-OrangePi-Console': 'connect' } });
  } catch { /* ignore */ }
  detachSerial(true);
});

sendButton.addEventListener('click', async () => {
  const text = sendText.value;
  let hex;
  if (sendMode.value === 'hex') {
    const clean = text.replace(/[^0-9a-fA-F]/g, '').toLowerCase();
    if (!clean || clean.length % 2) { mspLog('monitorLog', 'HEX 内容必须是非空且长度为偶数的十六进制'); return; }
    hex = clean;
  } else {
    const payload = text + (sendNewline.checked ? '\n' : '');
    hex = Array.from(new TextEncoder().encode(payload)).map((b) => b.toString(16).padStart(2, '0')).join('');
  }
  try {
    const response = await fetch('/api/serial/send', {
      method: 'POST', headers: { 'X-OrangePi-Console': 'connect' }, body: hex,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '发送失败');
    mspLog('monitorLog', `→ ${sendMode.value === 'hex' ? hex : text}`);
  } catch (error) {
    mspLog('monitorLog', `发送失败：${error.message}`);
  }
});

sendText.addEventListener('keydown', (event) => {
  if (event.key === 'Enter') sendButton.click();
});

if (location.hash === '#msp') selectTab('msp');

poll();
