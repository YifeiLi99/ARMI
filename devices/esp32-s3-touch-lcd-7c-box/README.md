# ARMI 私有心情窗固件

目标为 ESP32-S3-Touch-LCD-7C-BOX，基线 ESP-IDF 5.5.3、800×480 RGB 和 LVGL 9。首版只初始化 RGB 屏与 USB Serial/JTAG；触摸、网络、音频、麦克风和扬声器均不初始化。

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

串口协议为 `armi.mood-display.v2` JSON Lines，115200 8N1，单帧最多 512 字节。设备启动发送 `hello`；有效 `state` 应答 `ack/applied`。30 秒未收到有效状态后进入灰色闭眼离线脸。v2 将 Mood 的二十个情绪族一一映射到 `face_01` 至 `face_20` 的不透明显示编号；中性和离线是额外设备状态，不冒充情绪。串口仍不发送情绪名称。

表情由 80 ms 一帧的确定性像素动画状态机生成，不使用位图、Emoji 字体或直接显示颜文字字符串。固件先按 200×120 的虚拟像素构造眼睛、嘴和必要的泪滴、汗滴、腮红、问号等笔画，再以四倍整数像素绘制到 800×480 屏幕。背景永久保持纯黑；每个情绪族拥有固定颜色、独立颜表情造型和运动节奏，`energy` 只调节幅度与颜色呼吸。切换后的前 320 ms 逐帧淡入，离线脸保持暗灰色闭眼静止。

板级 RGB 引脚和时序核对自 Waveshare Apache-2.0 示例固定提交 `98618ce7e3154cd2f77051288e144008632bbd85`。板卡到货前尚未完成烧录、背光和实际显示验收。

没有板卡时，可从仓库根目录启动独立桌面预览器。它以 800×480 黑色画布复现当前颜表情动画参数，可切换表情、活跃度和自动轮播，不连接 Runtime 或串口：

```powershell
.\tools\start_mood_display_preview.ps1
```

`host_tests/` 含协议解析、30 秒离线状态机和逐帧动画参数的 C 测试；它需要宿主提供 CMake、C 编译器和 cJSON CMake package。当前仍须在装有 ESP-IDF 5.5.3 的环境执行目标板完整编译。
