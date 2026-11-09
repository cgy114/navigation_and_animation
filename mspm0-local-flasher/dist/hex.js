export const FLASH_SIZE = 0x20000; // MSPM0G3507 Main Flash: 128 KiB

export function parseHex(text) {
  const bytes = new Map();
  let base = 0;
  let ended = false;
  const lines = text.replace(/^\uFEFF/, '').split(/\r?\n/);
  for (let n = 0; n < lines.length; n++) {
    const line = lines[n].trim();
    if (!line) continue;
    if (ended) throw new Error(`第 ${n + 1} 行：结束记录后还有数据`);
    if (!/^:[0-9a-fA-F]+$/.test(line) || (line.length - 1) % 2) throw new Error(`第 ${n + 1} 行：不是有效 Intel HEX 记录`);
    const record = Uint8Array.from(line.slice(1).match(/../g).map(x => parseInt(x, 16)));
    const count = record[0];
    if (record.length !== count + 5) throw new Error(`第 ${n + 1} 行：记录长度不符`);
    if ((record.reduce((a, b) => a + b, 0) & 255) !== 0) throw new Error(`第 ${n + 1} 行：校验和错误`);
    const offset = (record[1] << 8) | record[2];
    const type = record[3];
    const data = record.slice(4, 4 + count);
    if (type === 0) {
      const start = base + offset;
      if (start < 0 || start + count > FLASH_SIZE) throw new Error(`第 ${n + 1} 行：地址超出 MSPM0G3507 主 Flash (0x00000–0x1FFFF)`);
      for (let i = 0; i < data.length; i++) {
        const address = start + i;
        if (bytes.has(address) && bytes.get(address) !== data[i]) throw new Error(`第 ${n + 1} 行：地址 0x${address.toString(16)} 有冲突数据`);
        bytes.set(address, data[i]);
      }
    } else if (type === 1) {
      if (count !== 0) throw new Error(`第 ${n + 1} 行：结束记录格式错误`);
      ended = true;
    } else if (type === 2) {
      if (count !== 2) throw new Error(`第 ${n + 1} 行：段地址格式错误`);
      base = ((data[0] << 8) | data[1]) * 16;
    } else if (type === 4) {
      if (count !== 2) throw new Error(`第 ${n + 1} 行：线性地址格式错误`);
      base = (((data[0] << 8) | data[1]) * 0x10000);
    } else if (type !== 3 && type !== 5) {
      throw new Error(`第 ${n + 1} 行：不支持的记录类型 ${type}`);
    }
  }
  if (!ended) throw new Error('HEX 缺少结束记录');
  if (!bytes.size) throw new Error('HEX 不含可烧录数据');

  // Group occupied 8-byte words. Unspecified bytes within a word retain erased value FF.
  const words = [...new Set([...bytes.keys()].map(address => address & ~7))].sort((a, b) => a - b);
  const segments = [];
  let start = words[0], previous = words[0];
  for (const word of words.slice(1)) {
    if (word !== previous + 8) {
      segments.push(makeSegment(start, previous + 8, bytes));
      start = word;
    }
    previous = word;
  }
  segments.push(makeSegment(start, previous + 8, bytes));
  return { segments, sourceBytes: bytes.size, programmedBytes: segments.reduce((n, s) => n + s.data.length, 0), first: words[0], last: words.at(-1) + 7 };
}

function makeSegment(start, end, bytes) {
  const data = new Uint8Array(end - start).fill(0xff);
  for (let address = start; address < end; address++) if (bytes.has(address)) data[address - start] = bytes.get(address);
  return { address: start, data };
}

export function* chunks(image, maxData = 256) {
  const size = Math.floor(maxData / 8) * 8;
  if (size < 8) throw new Error('BSL 缓冲区不足以写入 8 字节');
  for (const segment of image.segments) {
    for (let i = 0; i < segment.data.length; i += size) {
      yield { address: segment.address + i, data: segment.data.slice(i, i + size) };
    }
  }
}
