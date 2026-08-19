# ARMI 私有心情窗固件

目标为 ESP32-S3-Touch-LCD-7C-BOX，基线 ESP-IDF 5.5.3、800×480 RGB 和 LVGL 9。首版只初始化 RGB 屏与 USB Serial/JTAG；触摸、网络、音频、麦克风和扬声器均不初始化。

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

串口协议为 `armi.mood-display.v2` JSON Lines，115200 8N1，单帧最多 512 字节。设备启动发送 `hello`；有效 `state` 应答 `ack/applied`。30 秒未收到有效状态后进入灰色闭眼离线脸。v2 将 Mood 的二十个情绪族一一映射到 `face_01` 至 `face_20` 的不透明显示编号；中性和离线是额外设备状态，不冒充情绪。串口仍不发送情绪名称。

固件直接显示 Unicode 颜文字，不再绘制眼睛、嘴或装饰图形。二十个情绪族、中性和离线各自映射到一条固定且互不重复的现代颜文字；构建中嵌入的是由 Noto Sans SC 生成的最小 A8 抗锯齿文字资产，不携带完整字体，生成器会拒绝来源摘要不符、缺字或超出 720×160 显示边界的结果。背景永久保持纯黑；每个情绪族继续使用主机投影的固定颜色，`energy` 只调节轻微颜色呼吸，不改变文字。切换后的前 320 ms 淡入，离线颜文字保持暗灰色静止。

重新生成文字资产时，使用 `tools/generate_kaomoji_assets.py --font <NotoSansSC-VF.ttf>`。生成器固定核对源字体摘要；来源和许可记录见 `NOTICE`。

板级 RGB 引脚和时序核对自 Waveshare Apache-2.0 示例固定提交 `98618ce7e3154cd2f77051288e144008632bbd85`。板卡到货前尚未完成烧录、背光和实际显示验收。

没有板卡时，可从仓库根目录启动独立桌面预览器。它以 800×480 黑色画布复现当前文字、颜色呼吸与淡入效果，可切换表情、活跃度和自动轮播，不连接 Runtime 或串口：

```powershell
.\tools\start_mood_display_preview.ps1
```

`host_tests/` 含协议解析、30 秒离线状态机、Unicode 颜文字资产映射和显示参数的 C 测试；它需要宿主提供 CMake、C 编译器和 cJSON CMake package。当前仍须在装有 ESP-IDF 5.5.3 的环境执行目标板完整编译。
