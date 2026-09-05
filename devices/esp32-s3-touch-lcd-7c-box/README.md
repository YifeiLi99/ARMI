# ARMI 私有心情窗固件

目标为 ESP32-S3-Touch-LCD-7C-BOX，基线 ESP-IDF 5.5.3、800×480 RGB 和 LVGL 9。首版只初始化 RGB 屏与 USB Serial/JTAG；触摸、网络、音频、麦克风和扬声器均不初始化。

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

串口协议为 `armi.mood-display.v2` JSON Lines，115200 8N1，单帧最多 512 字节。主机连接后发送仅含 `type: identify` 和 `protocol_version` 的请求，设备返回 `hello`；握手不依赖连接时恰好收到启动消息。有效 `state` 应答 `ack/applied`；主机在状态变化时立即发送，未变化时每 10 秒续期。30 秒未收到有效状态后进入灰色闭眼离线脸。v2 将 Mood 的二十个情绪族一一映射到 `face_01` 至 `face_20` 的不透明显示编号；中性和离线是额外设备状态，不冒充情绪。串口仍不发送情绪名称。

固件直接显示 Unicode 颜文字，不再绘制眼睛、嘴或装饰图形。二十个情绪族、中性和离线各自映射到一条固定且互不重复的现代颜文字；构建中嵌入的是由 Noto Sans SC 生成的最小 A8 抗锯齿文字资产，不携带完整字体，生成器会拒绝来源摘要不符、缺字或超出 720×160 显示边界的结果。背景永久保持纯黑；每个情绪族继续使用主机投影的固定颜色，`energy` 只调节轻微颜色呼吸，不改变文字。切换后的前 320 ms 淡入，离线颜文字保持暗灰色静止。

重新生成文字资产时，使用 `tools/generate_kaomoji_assets.py --font <NotoSansSC-VF.ttf>`。生成器固定核对源字体摘要；来源和许可记录见 `NOTICE`。

板级 RGB 引脚、时序和扩展 IO 寄存器核对自 Waveshare Apache-2.0 示例固定提交 `98618ce7e3154cd2f77051288e144008632bbd85`。实板为 32 MB Octal Flash、16 MB Octal PSRAM；不能沿用参考示例中的 16 MB QIO 配置。屏幕通过 I2C 地址 `0x24` 的 EXIO0/2/5 控制复位、背光和电源，仅这些扩展引脚配置为输出。LVGL 使用单调时钟与 RGB 帧完成同步，等待 DMA 切换后才复用双缓冲。

`partitions.csv` 只定义 4 MiB 应用分区，固件不使用 NVS、网络或 OTA；`dependencies.lock` 固定组件来源。烧录使用构建生成的地址，不把单独的应用文件当作从 `0x00` 写入的合并镜像。端口无法同步时，按住 BOOT 重新接入 USB，松开 BOOT 后重新确认 COM 号，烧录完成按 RESET。恢复官方演示程序使用官方测试整包及其说明，不保证恢复原有设置。硬件连接和下载操作见 [官方指南](https://docs.waveshare.net/ESP32-S3-Touch-LCD-7C-BOX/Instructions-For-Use/)。

没有板卡时，可从仓库根目录启动独立桌面预览器。它以 800×480 黑色画布复现当前文字、颜色呼吸与淡入效果，可切换表情、活跃度和自动轮播，不连接 Runtime 或串口：

```powershell
.\tools\start_mood_display_preview.ps1
```

`host_tests/` 含协议解析、30 秒离线状态机、Unicode 颜文字资产映射和显示参数的 C 测试；它需要宿主提供 CMake、C 编译器和 cJSON CMake package。目标板构建使用 ESP-IDF 5.5.3 和锁定的 LVGL 9.3.0。主任务栈为 16 KiB，容纳 LVGL 渲染和协议处理；主机打开串口前将 DTR/RTS 设为低电平，避免连接时复位板子。

2026-09-05 在 32 MB Flash / 16 MB PSRAM 实板完成目标构建、烧录及写入校验；22 种显示状态均返回 `ack/applied`，连续超过 50 秒的心跳及随后重连保持相同 boot ID。操作者确认屏幕显示颜文字且发生切换。本轮未运行宿主 C 测试（未配置宿主 C 编译器），未逐项验收色差、亮度、撕裂和断电重连；这些结果不代表已接入真实 Runtime 心情状态。
