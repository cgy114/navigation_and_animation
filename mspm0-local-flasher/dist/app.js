import { parseHex, chunks } from './hex.js';
import { Bsl } from './bsl.js';
import { SerialConnection } from './serial.js';
import { parseWaveLine, PulseScope } from './waveform.js';

const $ = id => document.getElementById(id);
const serial = new SerialConnection(showIncoming, error => { setStatus(`串口断开：${error.message}`, 'error'); setScopeState('串口已断开'); updateButtons(); });
const scope = typeof $('scopeCanvas').getContext === 'function' ? new PulseScope($('scopeCanvas')) : null;
let image = null;
let busy = false;
let textDecoder = new TextDecoder();
let monitorLineBuffer = '';
let monitorPendingShown = 0;
let pidSupported = false;
let pendingPidCommand = '';
let logLines = 0;
const hex = value => `0x${value.toString(16).toUpperCase().padStart(5, '0')}`;

function log(message, kind = 'info') {
  const row = document.createElement('div');
  row.className = `log-row ${kind}`;
  const time = document.createElement('time');
  time.textContent = new Date().toLocaleTimeString('zh-CN', { hour12: false });
  const text = document.createElement('span');
  text.textContent = message;
  row.append(time, text);
  $('log').append(row);
  if (++logLines > 500) { $('log').firstElementChild.remove(); logLines--; }
  $('log').scrollTop = $('log').scrollHeight;
}
function setStatus(message, kind = 'info') {
  $('statusText').textContent = message;
  $('statusDot').className = `status-dot ${kind}`;
  log(message, kind);
}
function updateButtons() {
  $('connectBtn').disabled = busy || serial.isOpen;
  $('disconnectBtn').disabled = busy || !serial.isOpen;
  $('flashBtn').disabled = busy || !image;
  $('startBtn').disabled = busy || !serial.isOpen;
  $('sendBtn').disabled = busy || !serial.isOpen || serial.mode !== 'monitor';
  for (const id of ['pidReadBtn', 'pidApplyBtn'])
    $(id).disabled = busy || !serial.isOpen || serial.mode !== 'monitor';
  for (const id of ['pidSaveBtn', 'pidLoadBtn'])
    $(id).disabled = busy || !serial.isOpen || serial.mode !== 'monitor' || !pidSupported;
  $('monitorBaud').disabled = busy || serial.isOpen;
  $('flashBaud').disabled = busy;
  $('fileInput').disabled = busy;
  $('portLabel').textContent = serial.isOpen ? `已连接 · ${serial.mode === 'bsl' ? 'BSL' : '监视器'}` : '未连接';
}
function showIncoming(data) {
  const output = $('monitorOutput');
  const incoming = textDecoder.decode(data, { stream: true });
  monitorLineBuffer += incoming;
  const lines = monitorLineBuffer.split('\n');
  monitorLineBuffer = lines.pop();
  let visible = '';
  for (const line of lines) {
    const clean = line.trim();
    handlePidLine(clean);
    const isWaveLine = handleWaveLine(clean);
    if (!isWaveLine || $('showWaveRaw').checked) visible += `${line}\n`.slice(monitorPendingShown);
    monitorPendingShown = 0;
  }
  if (monitorLineBuffer.length > 4096) {
    visible += monitorLineBuffer.slice(monitorPendingShown);
    monitorLineBuffer = '';
    monitorPendingShown = 0;
  } else if (!$('rxHex').checked &&
      !(monitorLineBuffer.startsWith('RCW ') || 'RCW '.startsWith(monitorLineBuffer))) {
    visible += monitorLineBuffer.slice(monitorPendingShown);
    monitorPendingShown = monitorLineBuffer.length;
  }
  const part = $('rxHex').checked ? [...data].map(b => b.toString(16).toUpperCase().padStart(2, '0')).join(' ') + ' ' : visible;
  if (part) output.textContent += part;
  if (output.textContent.length > 100000) output.textContent = output.textContent.slice(-80000);
  if ($('autoScroll').checked) output.scrollTop = output.scrollHeight;
  $('rxCount').textContent = Number($('rxCount').textContent) + data.length;
}
function setScopeState(message, kind = '') {
  $('scopeState').textContent = message;
  $('scopeState').className = `scope-state ${kind}`;
}
function updateScopeReadouts(sample = null) {
  $('scopeHigh').textContent = sample ? `${sample.highUs} µs` : '—';
  $('scopeLow').textContent = sample ? `${sample.periodUs - sample.highUs} µs` : '—';
  $('scopePeriod').textContent = sample ? `${sample.periodUs} µs` : '—';
  $('scopeFrequency').textContent = sample ? `${(1000000 / sample.periodUs).toFixed(2)} Hz` : '—';
  $('scopeSamples').textContent = scope ? `${scope.received} / ${scope.dropped}` : '0 / 0';
}
function handleWaveLine(line) {
  if (line.startsWith('RCW ')) {
    const sample = parseWaveLine(line);
    if (!sample) { setScopeState('脉冲数据异常', 'missing'); return true; }
    if (scope && !scope.paused) {
      scope.push(sample);
      updateScopeReadouts(sample);
      setScopeState('实时采集', 'live');
    }
    return true;
  }
  if (line === 'RC PA28 NO PULSE' && scope && !scope.paused) setScopeState('PA28 无新脉冲', 'missing');
  else if (line.startsWith('RC PA28 high=') && scope && scope.received === 0)
    setScopeState('需要逐脉冲固件', 'missing');
  return false;
}
function handlePidLine(line) {
  const match = /^PID RAM (\d+) (\d+) (\d+) FLASH (?:(\d+) (\d+) (\d+)|NONE)$/.exec(line);
  if (match) {
    pidSupported = true;
    pendingPidCommand = '';
    $('pidRam').textContent = `Kp ${match[1]} · Ki ${match[2]} · Kd ${match[3]}`;
    $('pidFlash').textContent = match[4] === undefined ? '未保存' : `Kp ${match[4]} · Ki ${match[5]} · Kd ${match[6]}`;
    $('pidMessage').textContent = '参数已更新';
    updateButtons();
  } else if (line === 'ERR P' && ['P?', 'PL', 'PS'].includes(pendingPidCommand)) {
    pidSupported = false;
    pendingPidCommand = '';
    $('pidMessage').textContent = '当前固件不支持 Flash 参数命令；请烧录新版 smart_car.hex';
    updateButtons();
  } else if (/^(OK|ERR) P(?:S|L|D)?$/.test(line)) {
    pendingPidCommand = '';
    $('pidMessage').textContent = line.startsWith('OK') ? `${line} 成功` : `${line} 失败`;
  }
}
async function sendPid(command) {
  if (busy || !serial.isOpen || serial.mode !== 'monitor') return;
  try {
    const data = new TextEncoder().encode(`${command}\n`);
    pendingPidCommand = command.split(' ')[0];
    await serial.write(data);
    $('txCount').textContent = Number($('txCount').textContent) + data.length;
    if (pendingPidCommand) $('pidMessage').textContent = `已发送 ${command}`;
    log(`TX ${command}`, 'tx');
  } catch (error) { setStatus(`PID 指令发送失败：${error.message}`, 'error'); }
}
function applyPid() {
  const values = ['pidKp', 'pidKi', 'pidKd'].map(id => Number($(id).value));
  if (values.some(value => !Number.isInteger(value) || value < 0 || value > 100000)) {
    $('pidMessage').textContent = 'Kp、Ki、Kd 须为 0～100000 的整数';
    return;
  }
  return sendPid(`P ${values.join(' ')}`);
}
async function loadFile(file) {
  if (!file) return;
  try {
    image = parseHex(await file.text());
    $('fileName').textContent = file.name;
    $('fileDetails').textContent = `${image.sourceBytes.toLocaleString()} 字节数据 · ${image.programmedBytes.toLocaleString()} 字节待写入 · ${hex(image.first)}–${hex(image.last)}`;
    $('dropzone').classList.add('selected');
    setStatus('HEX 校验通过，准备烧录', 'success');
  } catch (error) {
    image = null;
    $('fileName').textContent = '选择 Intel HEX 固件';
    $('fileDetails').textContent = error.message;
    $('dropzone').classList.remove('selected');
    setStatus(`文件无效：${error.message}`, 'error');
  }
  updateButtons();
}
async function connectMonitor() {
  try {
    pidSupported = false;
    pendingPidCommand = '';
    $('pidRam').textContent = '待读取';
    $('pidFlash').textContent = '待读取';
    await serial.choosePort();
    serial.setMode('monitor');
    await serial.open(Number($('monitorBaud').value));
    textDecoder = new TextDecoder();
    monitorLineBuffer = '';
    monitorPendingShown = 0;
    if (scope) { scope.paused = false; scope.clear(); }
    $('scopePause').textContent = '暂停';
    updateScopeReadouts();
    setScopeState('等待 PA28 信号');
    setStatus(`串口已连接，${$('monitorBaud').value} bps`, 'success');
    await sendPid('P?');
  } catch (error) { setStatus(`连接失败：${error.message}`, 'error'); }
  updateButtons();
}
async function disconnect() {
  try { await serial.close(); setStatus('串口已断开'); }
  catch (error) { setStatus(`断开失败：${error.message}`, 'error'); }
  pidSupported = false;
  pendingPidCommand = '';
  setScopeState('串口已断开');
  updateButtons();
}
function passwordBytes() {
  const input = $('password').value.replace(/\s+/g, '');
  if (!/^[0-9a-fA-F]{64}$/.test(input)) throw new Error('BSL 密码须为 64 位十六进制字符（32 字节）');
  return Uint8Array.from(input.match(/../g).map(x => parseInt(x, 16)));
}
async function prepareBsl() {
  await serial.choosePort();
  if (serial.isOpen) await serial.close();
  serial.setMode('bsl');
  await serial.open(9600);
  const bsl = new Bsl(serial, message => log(message));
  await bsl.connect();
  const info = await bsl.info();
  log(`芯片 BSL 版本 0x${info.interpreter.toString(16)}，缓冲区 ${info.maxBuffer} 字节`);
  const baud = Number($('flashBaud').value);
  if (baud !== 9600) {
    await bsl.setBaud(baud);
    await serial.close();
    await serial.open(baud);
    log(`BSL 已切换到 ${baud} bps`);
  }
  await bsl.unlock(passwordBytes());
  log('BSL 解锁成功');
  return { bsl, info };
}
async function flash() {
  if (!image || busy) return;
  busy = true;
  updateButtons();
  $('progress').value = 0;
  $('progressLabel').textContent = '0%';
  try {
    // requestPort is reached directly from the click handler, retaining browser user activation.
    const { bsl, info } = await prepareBsl();
    setStatus('正在擦除主 Flash…');
    await bsl.erase();
    log('主 Flash 擦除成功');
    const blocks = [...chunks(image, Math.min(256, info.maxBuffer - 12))];
    for (let i = 0; i < blocks.length; i++) {
      await bsl.program(blocks[i].address, blocks[i].data);
      const percent = Math.round((i + 1) / blocks.length * 100);
      $('progress').value = percent;
      $('progressLabel').textContent = `${percent}%`;
      if (i === 0 || i === blocks.length - 1 || i % 16 === 15) log(`已写入 ${i + 1}/${blocks.length} 块`);
    }
    setStatus('烧录完成：所有写入块均收到 BSL 成功回执', 'success');
    log('可点击“启动应用”，然后用监视器连接应用串口波特率');
  } catch (error) {
    setStatus(`烧录失败：${error.message}`, 'error');
  } finally { busy = false; updateButtons(); }
}
async function startApplication() {
  if (busy) return;
  busy = true; updateButtons();
  try {
    if (serial.mode !== 'bsl') throw new Error('当前串口不在 BSL 模式，请先烧录');
    await new Bsl(serial).start();
    await serial.close();
    serial.setMode('monitor');
    await serial.open(Number($('monitorBaud').value));
    textDecoder = new TextDecoder();
    monitorLineBuffer = '';
    monitorPendingShown = 0;
    if (scope) { scope.paused = false; scope.clear(); }
    $('scopePause').textContent = '暂停';
    updateScopeReadouts();
    setScopeState('等待 PA28 信号');
    pidSupported = false;
    $('pidRam').textContent = '待读取';
    $('pidFlash').textContent = '待读取';
    setStatus(`应用已启动；监视器以 ${$('monitorBaud').value} bps 监听`, 'success');
  } catch (error) { setStatus(`启动应用失败：${error.message}`, 'error'); }
  finally { busy = false; updateButtons(); if (serial.isOpen && serial.mode === 'monitor') await sendPid('P?'); }
}
async function send() {
  if (!serial.isOpen || serial.mode !== 'monitor') return;
  try {
    const input = $('sendInput').value;
    let data;
    if ($('sendHex').checked) {
      const clean = input.replace(/[\s,]+/g, '');
      if (!clean || !/^(?:[0-9a-fA-F]{2})+$/.test(clean)) throw new Error('HEX 发送须为成对的十六进制字节');
      data = Uint8Array.from(clean.match(/../g).map(x => parseInt(x, 16)));
    } else {
      const ending = $('lineEnding').value;
      data = new TextEncoder().encode(input + (ending === 'crlf' ? '\r\n' : ending === 'lf' ? '\n' : ending === 'cr' ? '\r' : ''));
    }
    if (!data.length) return;
    await serial.write(data);
    $('txCount').textContent = Number($('txCount').textContent) + data.length;
    log(`TX ${data.length} 字节：${$('sendHex').checked ? [...data].map(x => x.toString(16).padStart(2, '0')).join(' ') : input}`, 'tx');
    if (!$('keepInput').checked) $('sendInput').value = '';
  } catch (error) { setStatus(`发送失败：${error.message}`, 'error'); }
}

$('connectBtn').addEventListener('click', connectMonitor);
$('disconnectBtn').addEventListener('click', disconnect);
$('flashBtn').addEventListener('click', flash);
$('startBtn').addEventListener('click', startApplication);
$('sendBtn').addEventListener('click', send);
$('pidReadBtn').addEventListener('click', () => sendPid('P?'));
$('pidApplyBtn').addEventListener('click', applyPid);
$('pidSaveBtn').addEventListener('click', () => sendPid('PS'));
$('pidLoadBtn').addEventListener('click', () => sendPid('PL'));
$('sendInput').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); send(); } });
$('fileInput').addEventListener('change', event => loadFile(event.target.files[0]));
$('dropzone').addEventListener('dragover', event => { event.preventDefault(); $('dropzone').classList.add('dragging'); });
$('dropzone').addEventListener('dragleave', () => $('dropzone').classList.remove('dragging'));
$('dropzone').addEventListener('drop', event => { event.preventDefault(); $('dropzone').classList.remove('dragging'); loadFile(event.dataTransfer.files[0]); });
$('clearMonitor').addEventListener('click', () => { $('monitorOutput').textContent = ''; $('rxCount').textContent = '0'; });
$('scopePause').addEventListener('click', () => {
  if (!scope) return;
  scope.paused = !scope.paused;
  $('scopePause').textContent = scope.paused ? '继续' : '暂停';
  if (scope.paused) setScopeState('已暂停', 'paused');
  else { scope.clear(); updateScopeReadouts(); setScopeState('等待 PA28 信号'); }
});
$('scopeClear').addEventListener('click', () => { scope?.clear(); updateScopeReadouts(); setScopeState('等待 PA28 信号'); });
$('scopeWindow').addEventListener('change', () => scope?.setWindow(Number($('scopeWindow').value)));
$('clearLog').addEventListener('click', () => { $('log').textContent = ''; logLines = 0; });
if (!('serial' in navigator)) setStatus('当前浏览器不支持 Web Serial，请使用桌面版 Chrome 或 Edge', 'error');
else if (window.location.protocol === 'file:') setStatus('本地文件模式：若浏览器阻止串口，请双击 start-local.cmd 打开 127.0.0.1 页面');
updateButtons();
