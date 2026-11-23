#!/usr/bin/env python3
import argparse
import json
import math
import sys
import time
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from threading import Lock

import cv2
import numpy as np
import yaml

ROS_SETUP = Path.home() / 'ros_setup'
PERCEPTION = Path.home() / 'catkin_ws/src/perception_preprocess'
sys.path[:0] = [str(ROS_SETUP), str(PERCEPTION / 'src')]

from adjust_brightness import decode_nv12_full_range
from apply_cam2_settings import CAM2_SENSOR, apply_controls
from cam2_preview import video_device
from perception_preprocess.white_balance import apply_white_balance

DEFAULT_WIDTH, DEFAULT_HEIGHT = 1280, 960
DEFAULT_FPS = 15


def capture_command(width, height):
    return [
        'v4l2-ctl', '-d', '/dev/video-camera0',
        f'--set-fmt-video=width={width},height={height},pixelformat=NV12',
        '--stream-mmap=4', '--stream-to=-',
    ]


class PreviewCorrection:
    def __init__(self, settings, gains):
        gamma = settings['preview_gamma']
        black = settings.get('preview_black_level', 0)
        saturation = settings.get('preview_saturation', 1)
        if not math.isfinite(gamma) or not 0 < gamma <= 1:
            raise ValueError('preview_gamma must be in (0, 1]')
        if not math.isfinite(black) or not 0 <= black < 255:
            raise ValueError('preview_black_level must be in [0, 255)')
        if not math.isfinite(saturation) or saturation < 0:
            raise ValueError('preview_saturation must be finite and nonnegative')

        levels = np.arange(256, dtype=np.uint8)
        neutral = np.repeat(levels[None, :, None], 3, axis=2)
        self.white_balance = apply_white_balance(neutral, gains)
        self.gamma = None
        if gamma != 1:
            curve = np.rint(255 * np.clip((levels.astype(float) - 16) / 239, 0, 1)**gamma)
            self.gamma = np.stack((curve, levels, levels), axis=-1)[None].astype(np.uint8)
        self.levels = None
        if black != 0 or saturation != 1:
            floats = levels.astype(np.float32)
            luma = (floats - black) * (255.0 / (255 - black))
            chroma = 128 + (floats - 128) * saturation
            self.levels = np.rint(np.clip(np.stack((luma, chroma, chroma), axis=-1), 0, 255))
            self.levels = self.levels[None].astype(np.uint8)

    def apply(self, image):
        image = cv2.LUT(image, self.white_balance)
        # Preserve the intermediate BGR clipping used by the saved CAM2 preview.
        for table in (self.gamma, self.levels):
            if table is not None:
                ycrcb = cv2.cvtColor(image, cv2.COLOR_BGR2YCrCb)
                image = cv2.cvtColor(cv2.LUT(ycrcb, table), cv2.COLOR_YCrCb2BGR)
        return image


def camera_frames(width, height, fps, quality):
    settings = json.loads((ROS_SETUP / 'cam2_preview.json').read_text())
    white_balance = yaml.safe_load((PERCEPTION / 'config/cam2_white_balance.yaml').read_text())
    gains = white_balance['pipeline']['white_balance_gains_bgr']
    correction = PreviewCorrection(settings, gains)
    sensor = video_device('v4l-subdev*', CAM2_SENSOR)
    apply_controls(sensor, settings)

    frame_bytes = width * height * 3 // 2
    interval = 1.0 / fps
    next_frame = 0.0
    with Popen(capture_command(width, height), stdout=PIPE, stderr=DEVNULL) as capture:
        try:
            for raw in iter(lambda: capture.stdout.read(frame_bytes), b''):
                if len(raw) != frame_bytes:
                    break
                now = time.monotonic()
                # Small tolerance: the sensor runs at ~30 fps, so a target of 30
                # would otherwise drop every other frame on scheduling jitter.
                if now + 0.004 < next_frame:
                    continue
                next_frame += interval
                if next_frame < now:
                    # Fell behind (slow frame or stalled pipe): resync instead of bursting.
                    next_frame = now + interval
                image = decode_nv12_full_range(np.frombuffer(raw, np.uint8), width, height)
                # The sensor is mounted sideways: show the scene upright.
                image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
                success, jpeg = cv2.imencode('.jpg', correction.apply(image),
                                             [cv2.IMWRITE_JPEG_QUALITY, quality])
                if success:
                    yield jpeg.tobytes()
        finally:
            capture.kill()


class CameraHandler(BaseHTTPRequestHandler):
    camera = Lock()
    width = DEFAULT_WIDTH
    height = DEFAULT_HEIGHT
    fps = DEFAULT_FPS
    quality = 80
    disable_nagle_algorithm = True

    def do_GET(self):
        if self.path == '/':
            page = (b'<!doctype html><meta name="viewport" content="width=device-width">'
                    b'<title>Orange Pi camera</title>'
                    b'<style>body{margin:0;background:#111}img{display:block;margin:auto;'
                    b'width:100vw;height:100vh;object-fit:contain}</style>'
                    b'<img src="/live.mjpg" alt="Orange Pi live camera">')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(page)))
            self.end_headers()
            self.wfile.write(page)
        elif self.path != '/live.mjpg':
            self.send_error(404)
        elif not self.camera.acquire(blocking=False):
            self.send_error(503, 'Camera already in use')
        else:
            try:
                self.stream_camera()
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
            finally:
                self.camera.release()

    def stream_camera(self):
        with closing(camera_frames(self.width, self.height, self.fps, self.quality)) as frames:
            first = next(frames, None)
            if first is None:
                self.send_error(503, 'Camera did not return frames')
                return
            self.connection.settimeout(5)
            self.send_response(200)
            self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.write_frame(first)
            for frame in frames:
                self.write_frame(frame)

    def write_frame(self, frame):
        header = f'--frame\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n'.encode('ascii')
        self.wfile.write(header + frame + b'\r\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('address')
    parser.add_argument('port', type=int)
    parser.add_argument('--width', type=int, default=DEFAULT_WIDTH)
    parser.add_argument('--height', type=int, default=DEFAULT_HEIGHT)
    parser.add_argument('--fps', type=float, default=DEFAULT_FPS)
    parser.add_argument('--quality', type=int, default=80, choices=range(30, 96))
    args = parser.parse_args()
    if not (32 <= args.width <= 4224 and 32 <= args.height <= 3136
            and args.width % 8 == 0 and args.height % 8 == 0):
        sys.exit('width/height must be multiples of 8 within the sensor range')
    if not 1 <= args.fps <= 60:
        sys.exit('fps must be between 1 and 60')
    CameraHandler.width = args.width
    CameraHandler.height = args.height
    CameraHandler.fps = args.fps
    CameraHandler.quality = args.quality
    cv2.setNumThreads(4)
    for attempt in range(180):
        try:
            server = ThreadingHTTPServer((args.address, args.port), CameraHandler)
            break
        except OSError as error:
            if error.errno != 99 or attempt == 179:
                sys.exit(str(error))
            time.sleep(1)
    with server:
        server.serve_forever()
