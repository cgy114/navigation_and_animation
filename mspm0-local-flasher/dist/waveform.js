export function parseWaveLine(line) {
  const match = /^RCW (\d+) (\d+) (\d+)$/.exec(line.trim());
  if (!match) return null;
  const sequence = Number(match[1]);
  const highUs = Number(match[2]);
  const periodUs = Number(match[3]);
  if (!Number.isSafeInteger(sequence) || !Number.isSafeInteger(highUs) ||
      !Number.isSafeInteger(periodUs) || periodUs < 1 || periodUs > 65535 ||
      highUs > periodUs) return null;
  return { sequence, highUs, periodUs };
}

export function waveformSegments(samples, windowUs) {
  const selected = [];
  let duration = 0;
  for (let i = samples.length - 1; i >= 0 && duration < windowUs; i--) {
    selected.unshift(samples[i]);
    duration += samples[i].periodUs;
  }
  let start = -duration;
  return selected.map(sample => {
    const segment = {
      start, highEnd: start + sample.highUs,
      end: start + sample.periodUs, gapBefore: !!sample.gapBefore,
    };
    start = segment.end;
    return segment;
  });
}

export class PulseScope {
  constructor(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.samples = [];
    this.windowUs = 100000;
    this.lastSequence = null;
    this.received = 0;
    this.dropped = 0;
    this.paused = false;
    this.framePending = false;
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => this.schedule());
      this.resizeObserver.observe(canvas);
    }
    this.schedule();
  }
  push(sample) {
    if (this.paused) return;
    if (this.lastSequence !== null && sample.sequence <= this.lastSequence) this.clear();
    const gapBefore = this.lastSequence !== null && sample.sequence > this.lastSequence + 1;
    if (gapBefore) this.dropped += sample.sequence - this.lastSequence - 1;
    this.lastSequence = sample.sequence;
    this.received++;
    this.samples.push({ ...sample, gapBefore });
    if (this.samples.length > 512) this.samples.splice(0, this.samples.length - 512);
    this.schedule();
  }
  clear() {
    this.samples = [];
    this.lastSequence = null;
    this.received = 0;
    this.dropped = 0;
    this.schedule();
  }
  setWindow(windowUs) {
    this.windowUs = windowUs;
    this.schedule();
  }
  schedule() {
    if (this.framePending || !this.ctx) return;
    this.framePending = true;
    const requestFrame = typeof requestAnimationFrame === 'function' ? requestAnimationFrame : callback => setTimeout(callback, 0);
    requestFrame(() => { this.framePending = false; this.draw(); });
  }
  draw() {
    const canvas = this.canvas;
    const ctx = this.ctx;
    const width = Math.max(canvas.clientWidth || 800, 320);
    const height = Math.max(canvas.clientHeight || 260, 180);
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#07101e';
    ctx.fillRect(0, 0, width, height);
    const left = 56;
    const right = width - 20;
    const top = 30;
    const bottom = height - 34;
    const highY = top + (bottom - top) * 0.23;
    const lowY = top + (bottom - top) * 0.78;
    ctx.lineWidth = 1;
    ctx.strokeStyle = '#233b50';
    for (let i = 0; i <= 10; i++) {
      const x = left + (right - left) * i / 10;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    }
    for (let i = 0; i <= 4; i++) {
      const y = top + (bottom - top) * i / 4;
      ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
    }
    ctx.fillStyle = '#809ab0';
    ctx.font = '11px ui-monospace, Consolas, monospace';
    ctx.textAlign = 'right';
    ctx.fillText('HIGH', left - 9, highY + 4);
    ctx.fillText('LOW', left - 9, lowY + 4);
    ctx.textAlign = 'center';
    for (let i = 0; i <= 10; i += 2) {
      const x = left + (right - left) * i / 10;
      ctx.fillText(`${Math.round((i / 10 - 1) * this.windowUs / 1000)} ms`, x, height - 11);
    }
    const segments = waveformSegments(this.samples, this.windowUs);
    const scale = (right - left) / this.windowUs;
    ctx.save();
    ctx.beginPath(); ctx.rect(left, top, right - left, bottom - top); ctx.clip();
    ctx.lineJoin = 'round';
    ctx.lineWidth = 2.5;
    ctx.strokeStyle = '#49e1c2';
    ctx.shadowColor = '#49e1c2';
    ctx.shadowBlur = 9;
    ctx.beginPath();
    for (const segment of segments) {
      const startX = right + segment.start * scale;
      const highX = right + segment.highEnd * scale;
      const endX = right + segment.end * scale;
      ctx.moveTo(startX, lowY);
      ctx.lineTo(startX, highY);
      ctx.lineTo(highX, highY);
      ctx.lineTo(highX, lowY);
      ctx.lineTo(endX, lowY);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.strokeStyle = '#ffad6b';
    ctx.lineWidth = 1.5;
    for (const segment of segments) {
      if (!segment.gapBefore) continue;
      const x = right + segment.start * scale;
      ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
    }
    ctx.restore();
    if (!segments.length) {
      ctx.fillStyle = '#678097';
      ctx.textAlign = 'center';
      ctx.font = '13px system-ui, sans-serif';
      ctx.fillText('连接串口并输入 PA28 信号后显示波形', (left + right) / 2, (top + bottom) / 2);
    }
  }
}
