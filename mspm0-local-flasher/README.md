# MSPM0G3507 本地串口烧录与监视器

无需第三方依赖的本地 Web Serial 工具。支持 Intel HEX 文件、MSPM0G3507 ROM UART BSL 烧录、串口接收与发送，以及常用波特率选择。

## 启动

**推荐：双击 [start-local.cmd](start-local.cmd)**。它会启动仅绑定本机的服务并打开 `http://127.0.0.1:8765/`。使用期间保持弹出的服务窗口打开，再用桌面版 Chrome 或 Edge 在设备列表中选择 USB 串口。

`dist/index.html` 是单文件页面，可双击查看，但部分 Chrome/Edge 版本会拒绝 `file://` 页面的串口权限；遇到此情况请使用上面的启动器。

也可以用 Node.js 18+ 启动本地服务：

```powershell
cd D:\workplace\mspm0-local-flasher
npm start
```

然后打开 <http://127.0.0.1:8765/>。页面和固件文件都只在本机处理；首次使用串口时浏览器会要求选择设备。修改源代码后运行 `npm run build`，重新生成可双击的单文件页面。

## 烧录步骤

1. 开发板自带 USB 串口时直接连接。使用 USB 转串口模块时，模块 TX 接芯片 PA11 (BSL_RX)、模块 RX 接 PA10 (BSL_TX)，并连接 GND。具体引脚以开发板的 BSL 配置为准。
2. 选择 `.hex` 文件。工具检查 Intel HEX 记录长度、校验和、重叠数据和主 Flash 地址范围。
3. 按住 BSL 键，按下 RST，松开 RST，再松开 BSL，并在 10 秒内点击“开始烧录”。
4. 工具先以 9600 bps 连接 ROM BSL，再切换到选择的 BSL 波特率；按需要使用 32 字节 BSL 密码解锁。出厂默认密码为全 `FF`。
5. 工具擦除主 Flash，再以 8 字节对齐的数据块写入。每块必须收到芯片的 ACK 与成功状态，进度才继续。完成后可点击“启动应用”。

**烧录会清除整个主 Flash。** 本工具只接受 MSPM0G3507 主 Flash `0x00000–0x1FFFF` 中的 HEX 数据，不写入 Non-main 配置区。未出现在 HEX 记录中的 8 字节块保持擦除状态；同一块中的空字节填充为 `FF`。

## 串口监视器

选择应用固件使用的波特率，然后点击“连接串口”。可切换文本/HEX 显示、文本/HEX 发送、行尾和自动滚动。连接期间需要更换波特率时，先断开再重新连接。若应用固件使用的 UART 引脚与 BSL 引脚不同，请将串口模块改接至应用引脚。

当前监视器默认 115200 bps，与工作区 `smart_car` 工程启动后调用的 `debug_uart_set_baud_115200()` 一致；烧录用 BSL 和应用调试串口的波特率可以不同。

## PA28 舵机信号波形

使用新版 `smart_car.hex` 时，将遥控器接收器的信号线接到 PA28，并将接收器 GND 与开发板 GND 相连。接收器按其原供电方式供电。串口监视器连接 115200 bps 后，页面下方的“舵机信号波形”面板会显示 PA28 的数字高低电平、最新脉宽、周期、频率以及收到和丢失的脉冲数。

固件每捕获一个完整周期发送一行 `RCW <序号> <高电平微秒> <周期微秒>`。上位机按每个周期的实测值绘图，而不是用半秒一次的摘要重复生成波形。可选 20/50/100/200 ms 时间窗、暂停和清除；逐脉冲文本默认从串口窗口隐藏，可勾选“在串口窗口显示逐脉冲数据”。原有 `RC PA28 high=...` 摘要继续显示。

该面板显示由数字边沿重建的时序，不能测量模拟电压幅度、上升沿形状或很短的毛刺。若面板提示“需要逐脉冲固件”，说明开发板仍在运行只输出摘要的旧版本。

## 验证与限制

运行 `npm test` 可检查 TI 文档示例帧、ACK 与执行状态处理，以及示例 HEX 的解析和 8 字节分块。测试不替代真实芯片烧录验收。页面显示“烧录完成”表示芯片对所有写入命令返回成功；本工具不进行 Flash 读回比较，因为 ROM BSL 的读出可由芯片配置禁用。

协议依据：[TI MSPM0 Bootloader User's Guide](https://www.ti.com/lit/ug/slau887a/slau887a.pdf)。交互参考：[嘉立创 MSPM0 串口烧录工具](https://wiki.lckfb.com/storage/html/mspm0-web-flasher/index.html)。

## AI / Codex MCP 接口

项目内的 `mcp_server.py` 提供本地 stdio MCP 服务，已注册为全局 Codex 服务器 `mspm0_serial`。Codex 配置位于 `C:\Users\OS\.codex\config.toml`；新建 Codex 聊天或重启客户端后可以发现新工具。服务器直接使用 Windows COM 口，无需打开网页。

| 工具 | 用途 |
| --- | --- |
| `list_serial_ports` | 列出可用 COM 口与 USB 设备描述 |
| `connect_serial` | 以指定波特率打开串口并开始后台缓存 |
| `read_serial` | 读取缓存的串口文本和原始 HEX 字节 |
| `capture_serial` | 一次调用完成连接、定时采样、释放串口 |
| `send_serial` | 发送 UTF-8 文本或 HEX 字节 |
| `disconnect_serial` | 释放 COM 口 |
| `flash_hex` | BSL 连接、解锁、擦除主 Flash、写入 HEX、可选启动应用与重连监视器 |

当前电脑发现 `COM10`（USB-SERIAL CH340）。使用示例：

> 列出串口，然后用 COM10、115200 波特率采集 3 秒，告诉我收到的文本和 HEX。

> 芯片已进入 BSL 模式。将 `D:\workplace\mspm0g3507_project1.hex` 烧录到 COM10，启动应用，然后以 115200 波特率读取串口信息。

`flash_hex` 会擦除 **主 Flash**。它先完整检查 HEX 文件地址与校验和，再连接芯片；每块写入都要求 BSL 返回成功状态。工具不擦除 Non-main 配置区，也不声称完成读回比较。使用 USB 转串口模块时，**BSL 进入按键流程仍需人工操作**：按住 BSL → 按 RST → 松 RST → 松 BSL，随后在 10 秒内调用烧录工具。若需要无人工按键的全自动进入 BSL，硬件必须额外将可控 GPIO 或 DTR/RTS 接到 BSL_INVOKE 与复位线路，并针对实际板卡实现控制序列。

一个 COM 口不能同时被浏览器监视器、Keil 和 MCP 服务占用。让 AI 访问 `COM10` 前，先在网页点击“断开”。

迁移或重装依赖时可执行 `powershell -ExecutionPolicy Bypass -File .\setup-mcp.ps1`；离线依赖已安装在项目的 `.vendor` 目录，运行时使用项目的 `.venv\Scripts\python.exe`。MCP 自测命令为 `.venv\Scripts\python.exe -m unittest discover -s test -p test_mcp_*.py -v`，端到端只读握手为 `.venv\Scripts\python.exe test\smoke_mcp.py`。
