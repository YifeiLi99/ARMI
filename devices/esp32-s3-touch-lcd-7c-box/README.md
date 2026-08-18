# ARMI 私有心情窗固件

目标为 ESP32-S3-Touch-LCD-7C-BOX，基线 ESP-IDF 5.5.3、800×480 RGB 和 LVGL 9。首版只初始化 RGB 屏与 USB Serial/JTAG；触摸、网络、音频、麦克风和扬声器均不初始化。

```powershell
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

串口协议为 `armi.mood-display.v1` JSON Lines，115200 8N1，单帧最多 512 字节。设备启动发送 `hello`；有效 `state` 应答 `ack/applied`。30 秒未收到有效状态后进入灰色闭眼离线脸。

板级 RGB 引脚和时序核对自 Waveshare Apache-2.0 示例固定提交 `98618ce7e3154cd2f77051288e144008632bbd85`。板卡到货前尚未完成烧录、背光和实际显示验收。

`host_tests/` 含协议解析和 30 秒离线状态机的 C 测试；它需要宿主提供 cJSON CMake package。当前仍须在装有 ESP-IDF 5.5.3 的环境执行目标板完整编译。
