# ARMI 私有心情窗固件

目标为 ESP32-S3-Touch-LCD-7C-BOX，基线 ESP-IDF 5.5.3、800×480 RGB 和 LVGL 9。首版只初始化 RGB 屏与 USB Serial/JTAG；触摸、网络、音频、麦克风和扬声器均不初始化。

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

串口协议为 `armi.mood-display.v2` JSON Lines，115200 8N1，单帧最多 512 字节。主机连接后发送仅含 `type: identify` 和 `protocol_version` 的请求，设备返回 `hello`；握手不依赖连接时恰好收到启动消息。有效 `state` 应答 `ack/applied`；主机在状态变化时立即发送，未变化时每 10 秒续期。30 秒未收到有效状态后进入灰色闭眼离线脸。v2 将 Mood 的二十个情绪族一一映射到 `face_01` 至 `face_20` 的不透明显示编号；中性和离线是额外设备状态，不冒充情绪。串口仍不发送情绪名称。

固件显示独立排布的几何电子脸，包含二十个情绪族、中性和离线共 22 种造型。以双眼和小嘴为主，按表情加入眉形、泪滴、面颊标记或离线睡眠符号，没有括号、手或外轮廓；双眼位置固定，嘴宽约 50～110px，以圆眼、挤眼、横线眼和不同嘴形区分情绪。几何图形在三倍分辨率绘制后等比例降采样，加入轻微扫描线和微光，生成 768×432 A8 资产，在 800×480 屏幕居中显示。造型定义见 [mood_face_geometry.py](../../tools/mood_face_geometry.py)，不依赖字体。目录中的颜文字仅作为文字索引，不参与绘制。背景永久纯黑；正式状态仍使用主机投影颜色，`energy` 调节轻微颜色呼吸，切换前 320ms 淡入，离线脸暗灰静止。独立演示的 `-Cyan` 选项统一青色，便于观察造型，不改变正式心情颜色合同。

当前中性为自然睁眼与短横嘴；离线为闭眼，并在右上角加入渐大的 `zzz`。悲伤使用泪滴，焦虑使用紧张眼形且没有眼泪；恐惧突出睁大的眼睛和张嘴，愤怒使用压低的实心眼形与咬紧的嘴。羞耻加入面颊短线，内疚使用低垂眼形和下弯嘴，嫉妒使用侧视，困惑使用不对称眉形。所有变体保留同一双眼中心和小嘴布局。

重新生成资产时，从仓库根运行 `.venv/Scripts/python.exe devices/esp32-s3-touch-lcd-7c-box/tools/generate_kaomoji_assets.py --preview .tmp/electronic-faces.png`。参考图只用于造型方向，未复制截图像素或游戏资产；第三方来源记录见 `NOTICE`。

板级 RGB 引脚、时序和扩展 IO 寄存器核对自 Waveshare Apache-2.0 示例固定提交 `98618ce7e3154cd2f77051288e144008632bbd85`。实板为 32 MB Octal Flash、16 MB Octal PSRAM；不能沿用参考示例中的 16 MB QIO 配置。屏幕通过 I2C 地址 `0x24` 的 EXIO0/2/5 控制复位、背光和电源，仅这些扩展引脚配置为输出。LVGL 使用单调时钟与 RGB 帧完成同步，等待 DMA 切换后才复用双缓冲。

`partitions.csv` 只定义 8 MiB 应用分区，容纳 22 张大尺寸 A8 资产及程序；固件不使用 NVS、网络或 OTA，`dependencies.lock` 固定组件来源。烧录使用构建生成的地址，不把单独的应用文件当作从 `0x00` 写入的合并镜像。端口无法同步时，按住 BOOT 重新接入 USB，松开 BOOT 后重新确认 COM 号，烧录完成按 RESET。恢复官方演示程序使用官方测试整包及其说明，不保证恢复原有设置。硬件连接和下载操作见 [官方指南](https://docs.waveshare.net/ESP32-S3-Touch-LCD-7C-BOX/Instructions-For-Use/)。

已烧录的板卡可以从仓库根运行[独立实板演示](../../tools/test_mood_display_board.ps1)，只连接指定 USB 串口，不启动 Runtime、不访问数据库、不修改环境配置。默认轮播 22 种状态，每种 4 秒，活跃度 70；每次发送均检查 applied 应答，长时间停留每 8 秒续期。结束或 Ctrl+C 停止时显示离线颜文字并释放串口。演示数据不代表 ARMI 当前心情。

```powershell
# 全套轮播；可用 -Cycles 3 连续播放三轮
.\tools\test_mood_display_board.ps1 -Port COM3

# 单独观察喜悦表情的高活跃度呼吸效果，持续 30 秒
.\tools\test_mood_display_board.ps1 -Port COM3 -Face joy -Energy 100 -Seconds 30

# 按指定顺序比较六种代表性的纯脸
.\tools\test_mood_display_board.ps1 -Port COM3 -Face interest,joy,neutral,sadness,anger,confusion -Seconds 6 -Cyan
```

`-Face` 使用 `joy`、`sadness`、`anger`、`neutral`、`offline` 等英文键，完整列表见 `python -m tools.test_mood_display_board --help`。如果 Runtime 或其他程序正在使用串口，先释放串口再演示；脚本不会强制关闭其他程序。

没有板卡时，可从仓库根目录启动独立桌面预览器。它直接读取固件的 A8 资产与目录，在 800×480 黑色画布上复现电子脸、颜色呼吸与淡入效果。默认统一青色，也可取消该选项查看正式投影配色；可切换表情、活跃度和自动轮播，不连接 Runtime 或串口：

```powershell
.\tools\start_mood_display_preview.ps1
```

`host_tests/` 含协议解析、30 秒离线状态机、电子脸资产映射和显示参数的 C 测试；它需要宿主提供 CMake、C 编译器和 cJSON CMake package。目标板构建使用 ESP-IDF 5.5.3 和锁定的 LVGL 9.3.0。主任务栈为 16 KiB，容纳 LVGL 渲染和协议处理；主机打开串口前将 DTR/RTS 设为低电平，避免连接时复位板子。

2026-09-05 在 32 MB Flash / 16 MB PSRAM 实板完成目标构建、烧录及写入校验；22 种显示状态均返回 `ack/applied`，连续超过 50 秒的心跳及随后重连保持相同 boot ID。操作者确认屏幕显示颜文字且发生切换。本轮未运行宿主 C 测试（未配置宿主 C 编译器），未逐项验收色差、亮度、撕裂和断电重连；这些结果不代表已接入真实 Runtime 心情状态。

同日电子脸版本完成 ESP-IDF 目标构建、实板烧录和写入校验，独立青色演示轮播全部 22 种状态且逐项获得 `ack/applied`，结束后显示离线脸并释放串口。6 项定向 Python 测试、Ruff、Pyright 和桌面资产加载检查通过；实板五官比例与审美效果等待操作者反馈，没有启动 ARMI Runtime。

同日按操作者反馈修订 11 张造型，定向测试增至 7 项并通过，Ruff、Pyright、目标构建和烧录校验通过；修订的 11 种状态独立轮播均获得 `ack/applied`，其余 11 张资产保持一致。此次实板观感仍等待操作者确认。
