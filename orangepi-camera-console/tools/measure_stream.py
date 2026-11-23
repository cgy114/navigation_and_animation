"""Measure effective MJPEG frame rate through a local port-forward."""
import http.client
import sys
import time

port = int(sys.argv[1]) if len(sys.argv) > 1 else 18878
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0


def read_frame(stream):
    while True:
        line = stream.readline()
        if not line:
            return None
        if line.startswith(b'--frame'):
            break
    length = None
    while True:
        line = stream.readline()
        if line in (b'\r\n', b'\n'):
            break
        if line.lower().startswith(b'content-length'):
            length = int(line.split(b':')[1])
    if length is None:
        return None
    data = b''
    while len(data) < length:
        chunk = stream.read(length - len(data))
        if not chunk:
            break
        data += chunk
    return data


conn = http.client.HTTPConnection('127.0.0.1', port, timeout=15)
conn.request('GET', '/live.mjpg')
response = conn.getresponse()
if response.status != 200:
    sys.exit(f'HTTP {response.status}')
first = read_frame(response)
if not first:
    sys.exit('no frame')
import io
import struct

# JPEG dimensions from the SOF0 marker
size = None
with io.BytesIO(first) as buffer:
    data = buffer.read()
index = 2
while index + 9 < len(data):
    if data[index] != 0xFF:
        index += 1
        continue
    marker = data[index + 1]
    if marker in (0xC0, 0xC2):
        height, width = struct.unpack('>HH', data[index + 5:index + 9])
        size = (width, height)
        break
    length = struct.unpack('>H', data[index + 2:index + 4])[0]
    index += 2 + length

started = time.monotonic()
deadline = started + seconds
frames = 1
while time.monotonic() < deadline:
    if not read_frame(response):
        break
    frames += 1
elapsed = time.monotonic() - started
print(f'{size[0]}x{size[1]}  {frames / elapsed:.1f} fps  ({frames} frames in {elapsed:.1f}s)')
conn.close()
