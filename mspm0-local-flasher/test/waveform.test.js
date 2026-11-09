import test from 'node:test';
import assert from 'node:assert/strict';
import { parseWaveLine, waveformSegments } from '../dist/waveform.js';

test('parses each captured pulse and rejects malformed timing', () => {
  assert.deepEqual(parseWaveLine('RCW 42 1524 13955'), {
    sequence: 42, highUs: 1524, periodUs: 13955,
  });
  assert.equal(parseWaveLine('RCW 43 16000 13955'), null);
  assert.equal(parseWaveLine('RCW 44 1500 0'), null);
  assert.equal(parseWaveLine('RC PA28 high=1524us period=13955us'), null);
});

test('places real captured pulse lengths on the time axis', () => {
  const segments = waveformSegments([
    { highUs: 1300, periodUs: 13955 },
    { highUs: 1700, periodUs: 13960 },
  ], 30000);
  assert.deepEqual(segments, [
    { start: -27915, highEnd: -26615, end: -13960, gapBefore: false },
    { start: -13960, highEnd: -12260, end: 0, gapBefore: false },
  ]);
});
