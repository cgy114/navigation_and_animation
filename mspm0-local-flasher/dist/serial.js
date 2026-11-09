export class SerialConnection {
  constructor(onData, onClose) {
    this.onData = onData;
    this.onClose = onClose;
    this.port = null;
    this.reader = null;
    this.mode = 'monitor';
    this.queue = [];
    this.waiter = null;
    this.closing = false;
  }
  get isOpen() { return !!this.port?.readable; }
  async choosePort() {
    if (!('serial' in navigator)) throw new Error('此浏览器不支持 Web Serial，请使用桌面版 Chrome 或 Edge');
    if (!window.isSecureContext) throw new Error('请直接打开本地 HTML，或通过 http://127.0.0.1 打开本工具');
    if (!this.port) {
      try { this.port = await navigator.serial.requestPort(); }
      catch (error) {
        if (error?.name === 'NotFoundError') throw new Error('未选择串口。请在设备列表中选择 USB 串口（如 CH340），并确认设备已连接电脑');
        if (error?.name === 'SecurityError' && window.location?.protocol === 'file:') throw new Error('浏览器拒绝本地文件的串口权限。请双击 start-local.cmd，通过 127.0.0.1 打开工具');
        throw error;
      }
    }
    return this.port;
  }
  async open(baudRate) {
    if (!this.port) throw new Error('尚未选择串口');
    if (this.isOpen) await this.close();
    this.closing = false;
    this.queue = [];
    await this.port.open({ baudRate, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none' });
    this.readTask = this.readLoop();
  }
  async readLoop() {
    let readError = null;
    try {
      while (this.port.readable && !this.closing) {
        this.reader = this.port.readable.getReader();
        try {
          while (true) {
            const { value, done } = await this.reader.read();
            if (done) break;
            if (value?.length) {
              if (this.mode === 'bsl') {
                this.queue.push(...value);
                this.flushWaiter();
              } else this.onData(value);
            }
          }
        } finally { this.reader.releaseLock(); this.reader = null; }
      }
    } catch (error) {
      readError = error;
    } finally {
      if (!this.closing) {
        this.rejectWaiter(new Error('串口连接已断开'));
        this.onClose(readError || new Error('设备已断开'));
      }
    }
  }
  setMode(mode) {
    this.mode = mode;
    this.queue = [];
    if (mode === 'monitor') this.rejectWaiter(new Error('已退出 BSL 模式'));
  }
  flushWaiter() {
    if (this.waiter && this.queue.length >= this.waiter.count) {
      const { count, resolve, timer } = this.waiter;
      clearTimeout(timer);
      this.waiter = null;
      resolve(Uint8Array.from(this.queue.splice(0, count)));
    }
  }
  rejectWaiter(error) {
    if (this.waiter) {
      clearTimeout(this.waiter.timer);
      this.waiter.reject(error);
      this.waiter = null;
    }
  }
  readExact(count, timeout = 2500) {
    if (!this.isOpen) return Promise.reject(new Error('串口未连接'));
    if (this.waiter) return Promise.reject(new Error('串口读取已在进行中'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.waiter = null;
        reject(new Error('等待芯片响应超时，请检查 BSL 模式、接线和波特率'));
      }, timeout);
      this.waiter = { count, resolve, reject, timer };
      this.flushWaiter();
    });
  }
  async write(data) {
    if (!this.port?.writable) throw new Error('串口未连接');
    const writer = this.port.writable.getWriter();
    try { await writer.write(data); } finally { writer.releaseLock(); }
  }
  async close() {
    this.closing = true;
    this.rejectWaiter(new Error('串口已关闭'));
    try { await this.reader?.cancel(); } catch {}
    await this.readTask;
    if (this.port?.readable || this.port?.writable) await this.port.close();
    this.queue = [];
  }
}
