# 香橙派摄像头 / 烧录 / 日志控制台

Windows 本地网页（`http://127.0.0.1:8765/`），通过 Tailscale + SSH 使用香橙派：

1. **实时画面**：OV13855 摄像头 MJPEG，可选分辨率与帧率，画面逆时针旋转 90°。
2. **实时日志**：摄像头服务、系统、内核、SSH 日志，支持自定义服务/文件/命令。
3. **烧录 / 串口**：在香橙派上直接烧录与香橙派相连的 MSPM0G3507，并做串口监视。

## 启动

从仓库根目录进入控制台目录，在 PowerShell 中设置香橙派的 Tailscale 地址或主机名，然后启动：

```powershell
cd orangepi-camera-console
$env:ORANGEPI_TAILSCALE_HOST = '<香橙派的 Tailscale 地址或主机名>'
python server.py --open
```

SSH 默认使用 `~/.ssh/id_ed25519`，可以用 `ORANGEPI_SSH_KEY` 指定已有的私钥文件，并提前在 OpenSSH 的 `known_hosts` 中登记板端主机密钥。也可以将变量设置在 Windows 用户环境中，再双击 `Start-OrangePi-Camera.cmd`。

如果使用备用热点，还需设置 `ORANGEPI_HOTSPOT_ADDRESS`（板端热点 IPv4 地址及子网长度）、`ORANGEPI_HOTSPOT_SSID`（Windows 已保存的热点名称）和 `ORANGEPI_WIFI_ADAPTER`（Windows 无线网卡名）。板端 NetworkManager 连接名称与 SSID 不同时，设置 `ORANGEPI_HOTSPOT_PROFILE`。使用可选的 `wifi-watchdog.sh` 时，在板端为它设置 `ORANGEPI_WIFI_PROFILE`。

## 烧录 / 串口

芯片的 USB 串口插在**香橙派**上，由香橙派执行 BSL 协议，本机只负责界面。

- 串口列表来自板端 `/dev/ttyUSB*`、`/dev/ttyACM*`、`/dev/ttyS*`。
- 烧录步骤：选择 `.hex` → 按住 BSL、按 RST、松 RST、松 BSL → 10 秒内点「开始烧录」。
- 先以 9600 连接 ROM BSL，读取设备信息后再切到所选 BSL 波特率；擦除主 Flash，按 8 字节对齐写入，最后可发送启动命令。
- 密码固定使用出厂默认 `FF × 32`；如需自定义可改 `server.py` 中 `stream_flash` 的 `--password`。
- 串口监视可切换文本/HEX 显示与发送、追加换行，并支持自动滚动。

## 依赖

- 本机：Windows OpenSSH、Python 3.8+、Tailscale 和已授权的 SSH 私钥
- 香橙派：`python3`、`python3-serial`（pyserial，已验证 3.4）、用户在 `dialout`/`tty` 组
- 将 `board/` 下的两个 Python 脚本安装到香橙派的 `~/.local/bin/`。使用直连热点时，还需要将 `camera-network.sh` 安装为 `~/.local/bin/orangepi-camera-network.sh`。
- 实时画面依赖板端的 `v4l2-ctl`、OpenCV、NumPy、PyYAML，以及已有的 `~/ros_setup` 和 `~/catkin_ws/src/perception_preprocess` 摄像头配置。

## 接口

| 路径 | 说明 |
| --- | --- |
| `GET /api/status` | 画面状态、分辨率/帧率、日志预设 |
| `POST /api/connect[?resolution=&fps=&restart=1]` | 启动/重启摄像头 |
| `GET /live.mjpg` | MJPEG 代理 |
| `GET /api/logs?source=` | SSE 日志流 |
| `GET /api/mspm0/ports` | 板端串口列表 |
| `POST /api/mspm0/upload` | 上传 HEX 固件 |
| `GET /api/mspm0/flash?port=&baud=&start=` | SSE 烧录进度 |
| `POST /api/serial/start?port=&baud=` | 打开串口监视 |
| `GET /api/serial/stream` | SSE 串口数据（`DATA <hex>`） |
| `POST /api/serial/send` | 发送 HEX 字节 |
| `POST /api/serial/stop` | 关闭串口 |

POST 需要 `X-OrangePi-Console: connect` 且 `Origin` 与 Host 一致；服务只监听 127.0.0.1。
