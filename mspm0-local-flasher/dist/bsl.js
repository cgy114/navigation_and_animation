export const BSL_BAUD = new Map([[4800, 1], [9600, 2], [19200, 3], [38400, 4], [57600, 5], [115200, 6], [1000000, 7], [2000000, 8], [3000000, 9]]);
const coreErrors = ['成功', 'BSL 已锁定', '密码错误', '多次密码错误', '未知命令', '无效内存范围', '无效命令', '禁止出厂重置', '出厂重置密码错误', '禁止读出', '地址或长度未按 8 字节对齐', '验证长度小于 1 KB'];
const ackErrors = { 0x51: '帧头错误', 0x52: 'CRC 错误', 0x53: '数据长度为零', 0x54: '数据包太大', 0x55: '未知通信错误', 0x56: '不支持此波特率' };

// TI BSL uses reflected CRC-32 with seed FFFFFFFF and no final XOR.
export function crc32(data) {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let i = 0; i < 8; i++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return crc >>> 0;
}
export function le32(value) { return [value & 255, value >>> 8 & 255, value >>> 16 & 255, value >>> 24 & 255]; }
export function packet(command, data = []) {
  const core = Uint8Array.of(command, ...data);
  return Uint8Array.of(0x80, core.length & 255, core.length >>> 8, ...core, ...le32(crc32(core)));
}
export function parseResponse(frame) {
  if (frame[0] !== 0x08) throw new Error('BSL 响应帧头错误');
  const len = frame[1] | frame[2] << 8;
  if (len < 1 || frame.length !== len + 7) throw new Error('BSL 响应长度错误');
  const core = frame.slice(3, 3 + len);
  const expected = le32(crc32(core));
  if (expected.some((b, i) => b !== frame[3 + len + i])) throw new Error('BSL 响应 CRC 错误');
  return { id: core[0], data: core.slice(1) };
}
export class Bsl {
  constructor(serial, log = () => {}) { this.serial = serial; this.log = log; }
  async command(id, data = [], response = null, timeout = 2500) {
    await this.serial.write(packet(id, data));
    const ack = (await this.serial.readExact(1, timeout))[0];
    if (ack !== 0) throw new Error(`BSL 拒绝命令 0x${id.toString(16)}：${ackErrors[ack] || `ACK 0x${ack.toString(16)}`}`);
    if (response === null) return null;
    const header = await this.serial.readExact(3, timeout);
    if (header[0] !== 0x08) throw new Error(`BSL 响应帧头错误：0x${header[0].toString(16)}`);
    const len = header[1] | header[2] << 8;
    if (len < 1 || len > 8192) throw new Error(`BSL 响应长度异常：${len}`);
    const frame = Uint8Array.of(...header, ...await this.serial.readExact(len + 4, timeout));
    const parsed = parseResponse(frame);
    if (parsed.id === 0x3b) {
      const status = parsed.data[0];
      if (status !== 0) throw new Error(`BSL 执行失败：${coreErrors[status] || `状态 0x${status.toString(16)}`}`);
      if (response !== 0x3b) throw new Error('BSL 返回了状态消息，未返回预期数据');
    } else if (parsed.id === 0x3a) {
      throw new Error(`BSL Flash 详细错误：${[...parsed.data].map(x => x.toString(16).padStart(2, '0')).join(' ')}`);
    } else if (parsed.id !== response) {
      throw new Error(`BSL 返回类型 0x${parsed.id.toString(16)}，预期 0x${response.toString(16)}`);
    }
    return parsed.data;
  }
  async connect() { await this.command(0x12); this.log('BSL 已连接'); }
  async info() {
    const data = await this.command(0x19, [], 0x31);
    if (data.length !== 24) throw new Error('BSL 设备信息长度不符');
    const maxBuffer = data[10] | data[11] << 8;
    if (maxBuffer < 32) throw new Error('BSL 报告的缓冲区过小');
    return { maxBuffer, interpreter: data[0] | data[1] << 8 };
  }
  async setBaud(rate) {
    if (!BSL_BAUD.has(rate)) throw new Error('BSL 不支持所选波特率');
    if (rate !== 9600) await this.command(0x52, [BSL_BAUD.get(rate)]);
  }
  async unlock(password) {
    if (password.length !== 32) throw new Error('BSL 密码必须为 32 字节');
    await this.command(0x21, password, 0x3b);
  }
  async erase() { await this.command(0x15, [], 0x3b, 15000); }
  async program(address, data) {
    if (address % 8 || data.length % 8) throw new Error('写入地址和长度须为 8 字节倍数');
    await this.command(0x20, [...le32(address), ...data], 0x3b, 5000);
  }
  async start() { await this.command(0x40); }
}
