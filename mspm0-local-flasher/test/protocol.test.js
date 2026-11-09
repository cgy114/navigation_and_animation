import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { Bsl, packet, parseResponse } from '../dist/bsl.js';
import { parseHex, chunks } from '../dist/hex.js';

const bytes = text => Uint8Array.from(text.split(' ').map(x => parseInt(x, 16)));

test('BSL frames match TI reference examples', () => {
  assert.deepEqual(packet(0x12), bytes('80 01 00 12 3A 61 44 DE'));
  assert.deepEqual(packet(0x15), bytes('80 01 00 15 99 F4 20 40'));
  assert.deepEqual(packet(0x52, [3]), bytes('80 02 00 52 03 6C 83 A2 AF'));
  assert.deepEqual(parseResponse(bytes('08 02 00 3B 00 38 02 94 82')), { id: 0x3b, data: Uint8Array.of(0) });
});

test('BSL waits for both packet ACK and successful core status', async () => {
  const writes = [];
  const input = [...bytes('00 08 02 00 3B 00 38 02 94 82')];
  const serial = { write: async data => writes.push(data), readExact: async count => Uint8Array.from(input.splice(0, count)) };
  await new Bsl(serial).erase();
  assert.deepEqual(writes[0], packet(0x15));
  assert.equal(input.length, 0);
});

test('sample MSPM0G3507 firmware parses and emits aligned blocks', async () => {
  const source = await readFile(new URL('../../mspm0g3507_project1.hex', import.meta.url), 'utf8');
  const image = parseHex(source);
  assert.ok(image.sourceBytes > 0);
  assert.equal(image.first, 0);
  const blocks = [...chunks(image, 256)];
  assert.ok(blocks.length > 0);
  for (const block of blocks) {
    assert.equal(block.address % 8, 0);
    assert.equal(block.data.length % 8, 0);
    assert.ok(block.data.length <= 256);
    assert.ok(block.address + block.data.length <= 0x20000);
  }
});

test('invalid HEX checksum and out-of-range address are rejected', () => {
  assert.throws(() => parseHex(':0100000000FE\n:00000001FF'), /校验和/);
  assert.throws(() => parseHex(':020000040002F8\n:01000000FF00\n:00000001FF'), /地址超出/);
});
