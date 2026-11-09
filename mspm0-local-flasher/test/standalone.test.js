import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

test('double-click HTML has inlined code and its connect button requests a port', async () => {
  const html = await readFile(new URL('../dist/index.html', import.meta.url), 'utf8');
  assert.match(html, /<style>[\s\S]*<\/style>/);
  assert.doesNotMatch(html, /<script[^>]+src=|<link[^>]+stylesheet/);
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  assert.equal(scripts.length, 1);
  const elements = new Map();
  const createElement = () => ({
    textContent: '', value: '9600', checked: false, disabled: false,
    classList: { add() {}, remove() {} },
    handlers: {},
    addEventListener(name, handler) { this.handlers[name] = handler; },
    append() {},
    get scrollHeight() { return 0; },
    set scrollTop(value) {},
  });
  const canvasContext = Object.fromEntries([
    'setTransform', 'fillRect', 'beginPath', 'moveTo', 'lineTo', 'stroke',
    'fillText', 'save', 'rect', 'clip', 'restore',
  ].map(name => [name, () => {}]));
  const document = {
    getElementById(id) {
      if (!elements.has(id)) {
        const element = createElement();
        if (id === 'scopeCanvas') element.getContext = () => canvasContext;
        elements.set(id, element);
      }
      return elements.get(id);
    },
    createElement,
  };
  let requests = 0;
  const sent = [];
  let resolveRead;
  const port = {
    readable: null, writable: null,
    async open() {
      this.readable = { getReader: () => ({ read: () => new Promise(resolve => { resolveRead = resolve; }), releaseLock() {} }) };
      this.writable = { getWriter: () => ({ async write(data) { sent.push(new TextDecoder().decode(data)); }, releaseLock() {} }) };
    },
  };
  const context = { document, window: { isSecureContext: true, location: { protocol: 'file:' } }, navigator: { serial: { async requestPort() { requests++; return port; } } }, TextDecoder, TextEncoder, Uint8Array, setTimeout, clearTimeout };
  vm.runInNewContext(scripts[0][1], context);
  assert.match(elements.get('statusText').textContent, /本地文件模式/);
  assert.equal(typeof elements.get('connectBtn').handlers.click, 'function');
  await elements.get('connectBtn').handlers.click();
  assert.equal(requests, 1);
  assert.match(elements.get('statusText').textContent, /串口已连接/);
  assert.deepEqual(sent, ['P?\n']);
  assert.equal(elements.get('pidLoadBtn').disabled, true);
  resolveRead({ value: new TextEncoder().encode('ERR P\r\n'), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.match(elements.get('pidMessage').textContent, /当前固件不支持/);
  assert.equal(elements.get('pidLoadBtn').disabled, true);
  resolveRead({ value: new TextEncoder().encode('PID RAM 4000 1500 0 FLASH NONE\r\n'), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(elements.get('pidRam').textContent, 'Kp 4000 · Ki 1500 · Kd 0');
  assert.equal(elements.get('pidFlash').textContent, '未保存');
  assert.equal(elements.get('pidLoadBtn').disabled, false);
  for (const [id, value] of [['pidKp', '3'], ['pidKi', '2'], ['pidKd', '0']]) {
    document.getElementById(id).value = value;
  }
  await elements.get('pidApplyBtn').handlers.click();
  assert.equal(sent.at(-1), 'P 3 2 0\n');
  resolveRead({ value: new TextEncoder().encode('ERR P\r\n'), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(elements.get('pidMessage').textContent, 'ERR P 失败');
  assert.equal(elements.get('pidRam').textContent, 'Kp 4000 · Ki 1500 · Kd 0');
  resolveRead({ value: new TextEncoder().encode('OK P\r\nPID RAM 3 2 0 FLASH NONE\r\n'), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(elements.get('pidRam').textContent, 'Kp 3 · Ki 2 · Kd 0');
  assert.equal(elements.get('pidMessage').textContent, '参数已更新');
  resolveRead({ value: new TextEncoder().encode('RCW 10 1524 13955\r\n'), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(elements.get('scopeHigh').textContent, '1524 µs');
  assert.equal(elements.get('scopePeriod').textContent, '13955 µs');
  assert.doesNotMatch(elements.get('monitorOutput').textContent, /RCW 10/);
  resolveRead({ value: new TextEncoder().encode('RCW 12 1530 '), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  resolveRead({ value: new TextEncoder().encode('13960\r\n'), done: false });
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(elements.get('scopeSamples').textContent, '2 / 1');
});
