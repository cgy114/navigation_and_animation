import argparse
import http.client
import ipaddress
import json
import os
import queue
import re
import shlex
import socket
import subprocess
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ASSETS = Path(__file__).with_name('dist')
TAILSCALE_IP = os.environ.get('ORANGEPI_TAILSCALE_HOST', '')
HOTSPOT_ADDRESS = os.environ.get('ORANGEPI_HOTSPOT_ADDRESS', '')
HOTSPOT_INTERFACE = ipaddress.IPv4Interface(HOTSPOT_ADDRESS) if HOTSPOT_ADDRESS else None
BOARD_IP = str(HOTSPOT_INTERFACE.ip) if HOTSPOT_INTERFACE else None
CAMERA_PORT = 8080
TUNNEL_HOST = '127.0.0.1'
TUNNEL_PORT = 18877
SSID = os.environ.get('ORANGEPI_HOTSPOT_SSID', '')
ADAPTER = os.environ.get('ORANGEPI_WIFI_ADAPTER', '')
KEY_FILE = Path(os.environ.get('ORANGEPI_SSH_KEY', '~/.ssh/id_ed25519')).expanduser()
SSH_EXE = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/OpenSSH/ssh.exe'
HOTSPOT_PROFILE = os.environ.get('ORANGEPI_HOTSPOT_PROFILE', SSID)
BOARD_NETWORK_HELPER = (
    f'ORANGEPI_HOTSPOT_PROFILE={shlex.quote(HOTSPOT_PROFILE)} '
    '/bin/bash "$HOME/.local/bin/orangepi-camera-network.sh"'
)
DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_FPS = 1280, 960, 15
# Each resolution lists the frame rates it may run at.
RESOLUTIONS = {
    '640x480': (640, 480, (25, 20, 15, 10, 5)),
    '800x600': (800, 600, (30, 25, 20, 15, 10, 5)),
    '1024x768': (1024, 768, (25, 20, 15, 10, 5)),
    '1280x960': (1280, 960, (25, 20, 15, 10, 5)),
    '1920x1440': (1920, 1440, (12, 10, 5)),
}


def start_camera_command(width, height, fps, quality=80):
    return (
        'systemctl --user stop orangepi-camera-live 2>/dev/null || true; '
        'systemctl --user reset-failed orangepi-camera-live 2>/dev/null || true; '
        'test -s "$HOME/.local/bin/orangepi-camera-live.py" && '
        'systemd-run --user --unit=orangepi-camera-live --property=Restart=on-failure '
        '--property=RestartSec=3s /usr/bin/python3 "$HOME/.local/bin/orangepi-camera-live.py" '
        f'0.0.0.0 {CAMERA_PORT} --width {width} --height {height} --fps {fps} --quality {quality}'
    )


def ssh(address, command):
    return subprocess.run(
        [str(SSH_EXE), '-i', str(KEY_FILE), '-o', 'IdentitiesOnly=yes',
         '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', f'HostKeyAlias={TAILSCALE_IP}', '-o', 'ConnectTimeout=4',
         f'orangepi@{address}', command],
        capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW,
    )


MSPM0_HELPER = 'python3 "$HOME/.local/bin/orangepi-mspm0.py"'
MSPM0_CACHE_DIR = '$HOME/.cache/orangepi-mspm0'
MSPM0_FIRMWARE = f'{MSPM0_CACHE_DIR}/firmware.hex'
PORT_RE = re.compile(r'^/dev/(ttyUSB|ttyACM|ttyS)[0-9]{1,3}$')

LOG_PRESETS = {
    'camera': ('摄像头服务', ['journalctl', '--user-unit', 'orangepi-camera-live.service',
                              '-n', '200', '-f', '-o', 'short-iso', '--no-pager']),
    'system': ('系统全部日志', ['journalctl', '-n', '200', '-f', '-o', 'short-iso', '--no-pager']),
    'kernel': ('内核日志', ['journalctl', '-k', '-n', '200', '-f', '-o', 'short-iso', '--no-pager']),
    'ssh': ('SSH / 登录', ['journalctl', '-u', 'ssh', '-n', '200', '-f', '-o', 'short-iso', '--no-pager']),
}

UNIT_RE = re.compile(r'^[A-Za-z0-9_.@:-]{1,128}$')
FILE_RE = re.compile(r'^/[A-Za-z0-9_./@:+-]{1,400}$')


def build_log_command(source):
    if source in LOG_PRESETS:
        return LOG_PRESETS[source][1]
    if source.startswith('unit:'):
        unit = source[5:]
        if not UNIT_RE.match(unit):
            raise ValueError('invalid unit name')
        return ['journalctl', '-u', unit, '-n', '200', '-f', '-o', 'short-iso', '--no-pager']
    if source.startswith('file:'):
        path = source[5:]
        if not FILE_RE.match(path) or '/..' in path:
            raise ValueError('invalid log file path')
        return ['tail', '-n', '200', '-F', path]
    if source.startswith('cmd:'):
        command = source[4:].strip()
        if not command or len(command) > 500:
            raise ValueError('invalid command')
        return ['bash', '-lc', command]
    raise ValueError('unknown log source')


def ssh_stream(command):
    """Start a long-running remote command; its merged output is read line by line."""
    return subprocess.Popen(
        [str(SSH_EXE), '-i', str(KEY_FILE), '-o', 'IdentitiesOnly=yes',
         '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', f'HostKeyAlias={TAILSCALE_IP}', '-o', 'ConnectTimeout=6',
         '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
         f'orangepi@{TAILSCALE_IP}', command],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def ssh_process(command, stdin_pipe=False):
    """Long-running remote command with merged output lines on stdout."""
    return subprocess.Popen(
        [str(SSH_EXE), '-i', str(KEY_FILE), '-o', 'IdentitiesOnly=yes',
         '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', f'HostKeyAlias={TAILSCALE_IP}', '-o', 'ConnectTimeout=6',
         '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3',
         f'orangepi@{TAILSCALE_IP}', command],
        stdin=subprocess.PIPE if stdin_pipe else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding='utf-8', errors='replace', bufsize=1,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def valid_port(port):
    return bool(PORT_RE.match(port or ''))


def mspm0_ports():
    result = ssh(TAILSCALE_IP, f'{MSPM0_HELPER} ports')
    if result.returncode != 0:
        raise OSError(result.stdout.strip() or '无法读取香橙派串口列表')
    return json.loads(result.stdout.strip().splitlines()[-1]).get('ports', [])


def mspm0_upload(firmware):
    size = len(firmware)
    command = (
        f'umask 077; mkdir -p "{MSPM0_CACHE_DIR}" || exit 1; '
        f'tmp=$(mktemp "{MSPM0_CACHE_DIR}/firmware.XXXXXX") || exit 1; '
        """trap 'rm -f "$tmp"' EXIT; """
        'cat > "$tmp" && received=$(wc -c < "$tmp") || exit 1; '
        f'if [ "$received" -ne {size} ]; then echo "Incomplete firmware upload" >&2; exit 1; fi; '
        f'mv -f -- "$tmp" "{MSPM0_FIRMWARE}"'
    )
    result = subprocess.run(
        [str(SSH_EXE), '-T', '-i', str(KEY_FILE), '-o', 'IdentitiesOnly=yes',
         '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', f'HostKeyAlias={TAILSCALE_IP}', '-o', 'ConnectTimeout=6',
         f'orangepi@{TAILSCALE_IP}', command],
        input=firmware, capture_output=True, timeout=60,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        message = (result.stderr.strip() or result.stdout.strip()).decode('utf-8', 'replace')
        raise OSError(message or '固件上传失败')
    return size


class SerialBridge:
    """One remote serial monitor process; commands are sent on its stdin."""

    def __init__(self):
        self.lock = threading.Lock()
        self.process = None
        self.lines = queue.Queue(maxsize=4000)
        self.port = None
        self.baud = None

    def running(self):
        return self.process is not None and self.process.poll() is None

    def start(self, port, baud):
        self.stop()
        with self.lock:
            self.lines = queue.Queue(maxsize=4000)
            command = (f'{MSPM0_HELPER} monitor --port {shlex.quote(port)} --baud {int(baud)}')
            self.process = ssh_process(command, stdin_pipe=True)
            self.port, self.baud = port, int(baud)
            threading.Thread(target=self._pump, args=(self.process, self.lines), daemon=True).start()

    @staticmethod
    def _pump(process, lines):
        try:
            for line in process.stdout:
                lines.put(line.rstrip('\n'))
        except (OSError, ValueError):
            pass
        finally:
            lines.put('__EOF__')

    def send(self, hexdata):
        if not self.running():
            raise RuntimeError('串口未连接')
        self.process.stdin.write('SEND %s\n' % hexdata)
        self.process.stdin.flush()

    def stop(self):
        process, self.process = self.process, None
        if process is not None and process.poll() is None:
            try:
                process.stdin.write('QUIT\n')
                process.stdin.flush()
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()


def port_open(host, port, timeout=0.5):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class CameraTunnel:
    """Keeps an SSH port forward from this PC to the board camera over Tailscale."""

    def __init__(self):
        self.lock = threading.Lock()
        self.process = None

    def alive(self):
        return self.process is not None and self.process.poll() is None

    def stop(self):
        with self.lock:
            self._stop_locked()

    def _stop_locked(self):
        if self.process is not None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    def ensure(self):
        with self.lock:
            if self.alive():
                return True
            self._stop_locked()
            if not KEY_FILE.is_file():
                return False
            self.process = subprocess.Popen(
                [str(SSH_EXE), '-i', str(KEY_FILE), '-o', 'IdentitiesOnly=yes',
                 '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                 '-o', f'HostKeyAlias={TAILSCALE_IP}', '-o', 'ConnectTimeout=4',
                 '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2',
                 '-o', 'ExitOnForwardFailure=yes',
                 '-N', '-L', f'{TUNNEL_HOST}:{TUNNEL_PORT}:127.0.0.1:{CAMERA_PORT}',
                 f'orangepi@{TAILSCALE_IP}'],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return wait_for(lambda: self.alive() and port_open(TUNNEL_HOST, TUNNEL_PORT), 8)


TUNNEL = CameraTunnel()


def request_camera(path, timeout):
    if port_open(TUNNEL_HOST, TUNNEL_PORT):
        connection = http.client.HTTPConnection(TUNNEL_HOST, TUNNEL_PORT, timeout=timeout)
        try:
            connection.connect()
            connection.request('GET', path)
            return connection, connection.getresponse(), 'tailscale'
        except Exception:
            connection.close()

    if not HOTSPOT_INTERFACE:
        raise OSError('No camera route')
    connection = http.client.HTTPConnection(BOARD_IP, CAMERA_PORT, timeout=timeout)
    try:
        connection.connect()
        source_ip = connection.sock.getsockname()[0]
        if ipaddress.IPv4Address(source_ip) not in HOTSPOT_INTERFACE.network:
            raise OSError('No hotspot route')
        connection.request('GET', path)
        return connection, connection.getresponse(), 'hotspot'
    except Exception:
        connection.close()
        raise


def camera_route():
    try:
        connection, response, route = request_camera('/', timeout=0.7)
        try:
            with response:
                return route if response.status == 200 else None
        finally:
            connection.close()
    except (OSError, http.client.HTTPException):
        return None


def hotspot_ssh_reachable():
    if not HOTSPOT_INTERFACE:
        return False
    try:
        with socket.create_connection((BOARD_IP, 22), timeout=0.5) as link:
            return ipaddress.IPv4Address(link.getsockname()[0]) in HOTSPOT_INTERFACE.network
    except OSError:
        return False


def wlan(*args):
    return subprocess.run(
        ['netsh.exe', 'wlan', *args, f'interface={ADAPTER}'],
        capture_output=True, timeout=8, creationflags=subprocess.CREATE_NO_WINDOW,
    )


def join_hotspot():
    wlan('connect', f'name={SSID}', f'ssid={SSID}')


def hotspot_visible():
    return SSID.encode('ascii') in wlan('show', 'networks').stdout


def wait_for(probe, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if probe():
            return True
        time.sleep(1)
    return False


class ConnectionControl:
    def __init__(self):
        self.lock = threading.Lock()
        self.busy = False
        self.message = ''
        self.viewers = 0
        self.width = DEFAULT_WIDTH
        self.height = DEFAULT_HEIGHT
        self.fps = DEFAULT_FPS

    def start(self, allow_hotspot=True, mode=None, fps=None, force=False):
        with self.lock:
            if self.busy:
                return
            if mode in RESOLUTIONS:
                width, height, rates = RESOLUTIONS[mode]
                self.width, self.height = width, height
                if self.fps not in rates:
                    self.fps = rates[0]
            rates = RESOLUTIONS[f'{self.width}x{self.height}'][2]
            try:
                requested = int(fps)
            except (TypeError, ValueError):
                requested = None
            if requested in rates:
                self.fps = requested
            elif self.fps not in rates:
                self.fps = rates[0]
            self.busy = True
            self.message = '正在检查 USB 网卡和摄像头服务…'
        threading.Thread(target=self.connect, args=(allow_hotspot, force), daemon=True).start()

    def refresh(self):
        with self.lock:
            if self.busy:
                return
            self.busy = True
            self.message = '正在重新连接画面通道…'
        threading.Thread(target=self._refresh, daemon=True).start()

    def _refresh(self):
        try:
            if camera_route() or (TUNNEL.ensure() and wait_for(camera_route, 8)):
                self.finish('')
                return
            self.finish(self.reconnect(allow_hotspot=False))
        except (OSError, subprocess.SubprocessError) as error:
            print(f'Refresh helper error: {error}', flush=True)
            self.finish('连接操作未完成。请确认香橙派已开机后重试。')

    def progress(self, message):
        with self.lock:
            self.message = message

    def finish(self, message):
        with self.lock:
            self.busy = False
            self.message = message

    def connect(self, allow_hotspot=True, force=False):
        try:
            self.finish(self.reconnect(allow_hotspot, force))
        except (OSError, subprocess.SubprocessError) as error:
            print(f'Connection helper error: {error}', flush=True)
            self.finish('连接操作未完成。请确认 USB 网卡已插入、香橙派已开机后重试。')

    def reconnect(self, allow_hotspot=True, force=False):
        if not force and camera_route():
            return ''
        if not KEY_FILE.is_file():
            return '本机找不到已配置的 SSH 密钥。'

        command = start_camera_command(self.width, self.height, self.fps)
        self.progress('正在通过 Tailscale 启动香橙派摄像头…')
        result = ssh(TAILSCALE_IP, command)
        if result.returncode == 0:
            self.progress('正在建立到香橙派的画面通道…')
            if TUNNEL.ensure() and wait_for(camera_route, 15):
                return ''
            return '香橙派已连上，但摄像头画面未就绪。请检查摄像头是否被其他程序占用。'

        if not (allow_hotspot and HOTSPOT_INTERFACE and SSID and ADAPTER):
            return '香橙派暂时不可达。请确认 Tailscale 在线后重试。'

        if not hotspot_ssh_reachable():
            join_hotspot()
        if wait_for(hotspot_ssh_reachable, 6):
            result = ssh(BOARD_IP, command)
            if result.returncode == 0 and wait_for(camera_route, 12):
                return ''
            return 'USB 热点已连接，但摄像头服务未启动。'

        result = ssh(TAILSCALE_IP, f'{BOARD_NETWORK_HELPER} start')
        checkpoint = re.search(r'/org/freedesktop/NetworkManager/Checkpoint/\d+', result.stdout)
        if result.returncode != 0 or checkpoint is None:
            return '暂时找不到香橙派。请确认香橙派和 Tailscale 在线，并检查 USB 网卡。'
        self.progress('正在扫描香橙派热点，首次连接可能需要一分钟…')
        time.sleep(5)
        visible = wait_for(lambda: hotspot_ssh_reachable() or hotspot_visible(), 80)
        if visible and not hotspot_ssh_reachable():
            join_hotspot()
        self.progress('正在等待 USB 网卡取得地址和摄像头上线…')
        if not wait_for(camera_route, 45):
            return 'USB 网卡未收到画面。香橙派将自动恢复原有 Wi-Fi。'

        result = ssh(BOARD_IP, f'{BOARD_NETWORK_HELPER} confirm {checkpoint.group()}')
        if result.returncode != 0:
            return '画面已连通，但未能确认热点切换，香橙派可能会恢复原有 Wi-Fi。'
        return ''


class CameraHandler(BaseHTTPRequestHandler):
    disable_nagle_algorithm = True

    def log_request(self, code='-', size='-'):
        if self.path not in ('/api/status', '/api/logs', '/api/serial/status',
                             '/api/mspm0/ports', '/api/mspm0/flash', '/api/serial/stream'):
            super().log_request(code, size)

    def same_host(self):
        port = self.server.server_port
        return self.headers.get('Host') in (f'127.0.0.1:{port}', f'localhost:{port}')

    def send_body(self, content_type, body, status=200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data, status=200):
        self.send_body('application/json; charset=utf-8', json.dumps(data).encode('utf-8'), status)

    def do_POST(self):
        origin = f"http://{self.headers.get('Host')}"
        if (not self.same_host() or self.headers.get('Origin') != origin
                or self.headers.get('X-OrangePi-Console') != 'connect'):
            self.send_error(403)
        elif urlsplit(self.path).path == '/api/connect':
            query = parse_qs(urlsplit(self.path).query)
            resolution = (query.get('resolution') or [None])[0]
            fps = (query.get('fps') or [None])[0]
            force = (query.get('restart') or [''])[0] == '1'
            self.server.control.start('mode=tailscale' not in query, resolution, fps, force)
            self.send_json({'accepted': True}, 202)
        elif urlsplit(self.path).path == '/api/refresh':
            self.server.control.refresh()
            self.send_json({'accepted': True}, 202)
        elif urlsplit(self.path).path == '/api/mspm0/upload':
            try:
                length = int(self.headers.get('Content-Length') or 0)
            except ValueError:
                length = 0
            if length <= 0 or length > 4 * 1024 * 1024:
                self.send_json({'error': '固件大小异常'}, 400)
                return
            firmware = self.rfile.read(length)
            if len(firmware) != length:
                self.send_json({'error': '固件上传不完整'}, 400)
                return
            try:
                self.send_json({'bytes': mspm0_upload(firmware)})
            except (OSError, subprocess.SubprocessError) as error:
                self.send_json({'error': str(error)}, 502)
        elif urlsplit(self.path).path == '/api/serial/start':
            query = parse_qs(urlsplit(self.path).query)
            port = (query.get('port') or [''])[0]
            try:
                baud = int((query.get('baud') or ['115200'])[0])
            except ValueError:
                baud = 0
            if not valid_port(port) or not 300 <= baud <= 4000000:
                self.send_json({'error': '串口参数无效'}, 400)
                return
            self.server.serial_bridge.start(port, baud)
            self.send_json({'ok': True})
        elif urlsplit(self.path).path == '/api/serial/send':
            length = int(self.headers.get('Content-Length') or 0)
            try:
                hexdata = self.rfile.read(length).decode('ascii').strip()
                bytes.fromhex(hexdata)
                self.server.serial_bridge.send(hexdata)
                self.send_json({'ok': True})
            except (ValueError, RuntimeError, OSError) as error:
                self.send_json({'error': str(error)}, 400)
        elif urlsplit(self.path).path == '/api/serial/stop':
            self.server.serial_bridge.stop()
            self.send_json({'ok': True})
        else:
            self.send_error(404)

    def do_GET(self):
        if not self.same_host():
            self.send_error(403)
            return
        path = urlsplit(self.path).path
        control = self.server.control
        if path == '/api/status':
            route = camera_route()
            with control.lock:
                self.send_json({'app': 'orangepi-camera-console', 'ready': bool(route),
                                'route': route, 'connecting': control.busy,
                                'board_host': TAILSCALE_IP, 'hotspot_ssid': SSID,
                                'message': control.message, 'streaming': bool(control.viewers),
                                'resolution': f'{control.width}x{control.height}',
                                'fps': control.fps,
                                'presets': {key: value[0] for key, value in LOG_PRESETS.items()}})
        elif path == '/api/logs':
            source = (parse_qs(urlsplit(self.path).query).get('source') or ['camera'])[0]
            self.stream_logs(source)
        elif path == '/api/mspm0/ports':
            try:
                self.send_json({'ports': mspm0_ports()})
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                self.send_json({'error': str(error)}, 502)
        elif path == '/api/mspm0/flash':
            self.stream_flash(parse_qs(urlsplit(self.path).query))
        elif path == '/api/serial/status':
            bridge = self.server.serial_bridge
            self.send_json({'running': bridge.running(), 'port': bridge.port, 'baud': bridge.baud})
        elif path == '/api/serial/stream':
            self.stream_serial()
        elif path == '/live.mjpg':
            self.stream()
        elif path in STATIC_FILES:
            name, content_type = STATIC_FILES[path]
            self.send_body(content_type, (ASSETS / name).read_bytes())
        else:
            self.send_error(404)

    def stream(self):
        try:
            connection, response, _ = request_camera('/live.mjpg', timeout=8)
        except (OSError, http.client.HTTPException):
            self.send_error(503, 'Camera unavailable')
            return
        control = self.server.control
        with response:
            try:
                content_type = response.getheader('Content-Type', '')
                if response.status != 200 or not content_type.startswith('multipart/x-mixed-replace;'):
                    self.send_error(503, 'Camera unavailable or already in use')
                    return
                self.connection.settimeout(6)
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with control.lock:
                    control.viewers += 1
                try:
                    while chunk := response.read1(65536):
                        self.wfile.write(chunk)
                finally:
                    with control.lock:
                        control.viewers -= 1
            except (OSError, http.client.HTTPException):
                pass
            finally:
                connection.close()

    def sse_start(self, meta):
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()
        self.send_event('meta', meta)

    def send_event(self, event, payload):
        frame = f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
        self.wfile.write(frame.encode('utf-8'))
        self.wfile.flush()

    def stream_flash(self, query):
        port = (query.get('port') or [''])[0]
        try:
            baud = int((query.get('baud') or ['115200'])[0])
        except ValueError:
            baud = 0
        allowed = (4800, 9600, 19200, 38400, 57600, 115200, 1000000, 2000000, 3000000)
        if not valid_port(port) or baud not in allowed:
            self.send_json({'error': '烧录参数无效'}, 400)
            return
        start = (query.get('start') or ['1'])[0] != '0'
        command = (f'{MSPM0_HELPER} flash --port {shlex.quote(port)} '
                   f'--hex-file "{MSPM0_FIRMWARE}" --baud {baud} --password {"ff" * 32}'
                   + (' --start' if start else ''))
        try:
            process = ssh_process(command)
        except OSError as error:
            self.send_json({'error': f'无法启动 SSH: {error}'}, 500)
            return
        self.stream_process(process, {'port': port, 'baud': baud})

    def stream_process(self, process, meta):
        self.sse_start(meta)
        lines = queue.Queue(maxsize=5000)

        def reader():
            try:
                for line in process.stdout:
                    try:
                        lines.put(line.rstrip('\n'), timeout=30)
                    except queue.Full:
                        pass
            finally:
                lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        try:
            while True:
                try:
                    line = lines.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
                    continue
                if line is None:
                    self.send_event('end', {'reason': '完成'})
                    break
                self.send_event('line', {'line': line})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()

    def stream_serial(self):
        bridge = self.server.serial_bridge
        if not bridge.running():
            self.send_json({'error': '串口未连接'}, 409)
            return
        self.sse_start({'port': bridge.port, 'baud': bridge.baud})
        lines = bridge.lines
        try:
            while True:
                try:
                    line = lines.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
                    continue
                if line == '__EOF__':
                    self.send_event('end', {'reason': '串口已断开'})
                    break
                self.send_event('line', {'line': line})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def stream_logs(self, source):
        try:
            remote = build_log_command(source)
        except ValueError as error:
            self.send_json({'error': str(error)}, 400)
            return
        command = shlex.join(remote)
        try:
            process = ssh_stream(command)
        except OSError as error:
            self.send_json({'error': f'无法启动 SSH: {error}'}, 500)
            return

        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Accel-Buffering', 'no')
        self.end_headers()

        def send_event(event, payload):
            frame = f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'
            self.wfile.write(frame.encode('utf-8'))
            self.wfile.flush()

        lines = queue.Queue(maxsize=5000)

        def reader():
            try:
                for line in process.stdout:
                    try:
                        lines.put(line.rstrip('\n'), timeout=30)
                    except queue.Full:
                        pass
            finally:
                lines.put(None)

        threading.Thread(target=reader, daemon=True).start()
        try:
            send_event('meta', {'source': source, 'command': command})
            while True:
                try:
                    line = lines.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
                    continue
                if line is None:
                    send_event('end', {'reason': '远程日志流已结束'})
                    break
                send_event('line', {'line': line})
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


STATIC_FILES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
    '/styles.css': ('styles.css', 'text/css; charset=utf-8'),
}


def existing_console(port):
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request('GET', '/api/status')
        with connection.getresponse() as response:
            return response.status == 200 and json.load(response).get('app') == 'orangepi-camera-console'
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    if not TAILSCALE_IP:
        parser.error('Set ORANGEPI_TAILSCALE_HOST to your Orange Pi Tailscale address or hostname')
    url = f'http://127.0.0.1:{args.port}/'
    try:
        server = ThreadingHTTPServer(('127.0.0.1', args.port), CameraHandler)
    except OSError:
        if not existing_console(args.port):
            raise
        if args.open:
            webbrowser.open(url)
    else:
        server.daemon_threads = True
        server.control = ConnectionControl()
        server.serial_bridge = SerialBridge()
        print(f'Orange Pi Camera Console: {url}', flush=True)
        if args.open:
            threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
        with server:
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
