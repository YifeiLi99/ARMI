"""Demonstrate the physical USB display with test data, without starting Runtime."""

from __future__ import annotations

import argparse
import math
import time
from dataclasses import replace
from uuid import uuid4

import serial
from armi_adapter_esp32_display import DisplayExpression, DisplayState
from armi_adapter_esp32_display.wire import (
    PROTOCOL_VERSION,
    decode_frame,
    encode_identify,
    encode_state,
    parse_hello,
)

from tools.mood_display_preview import FACES, FaceSpec
from tools.mood_face_geometry import CYAN


def positive_seconds(value: str) -> float:
    seconds = float(value)
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError("停留时间必须是大于 0 的有限秒数")
    return seconds


def apply_face(port: serial.Serial, face: FaceSpec, energy: int) -> None:
    state_id = str(uuid4())
    state = DisplayState(
        1, DisplayExpression[face.key.upper()], face.color, "#000000", energy
    )
    frame = encode_state(state_id, state)
    if port.write(frame) != len(frame):
        raise RuntimeError("串口未完整写入状态帧")
    ack = decode_frame(port.read_until(b"\n", 513))
    if ack != {
        "type": "ack",
        "protocol_version": PROTOCOL_VERSION,
        "state_id": state_id,
        "status": "applied",
    }:
        raise RuntimeError(f"设备未确认应用测试状态: {ack}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="实板串口 (例如 COM3)")
    parser.add_argument("--seconds", type=positive_seconds, default=4.0)
    parser.add_argument("--energy", type=int, choices=range(101), default=70)
    parser.add_argument("--face", nargs="+", choices=[face.key for face in FACES])
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--cyan", action="store_true", help="统一青色观察五官造型")
    parser.add_argument("--device-id", default="armi-mood-window-7c-1")
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("--cycles 必须大于 0")
    by_key = {face.key: face for face in FACES}
    faces = FACES if args.face is None else [by_key[key] for key in args.face]
    if args.cyan:
        faces = [replace(face, color=CYAN) for face in faces]
    port = serial.Serial(port=None, baudrate=115200, timeout=2, write_timeout=2)
    port.dtr = False
    port.rts = False
    port.port = args.port
    with port:
        request = encode_identify()
        if port.write(request) != len(request):
            raise RuntimeError("串口未完整写入身份查询")
        identity = parse_hello(port.read_until(b"\n", 513))
        if identity.device_id != args.device_id:
            raise RuntimeError(f"设备身份不匹配: {identity.device_id}")
        print(
            f"已连接 {identity.device_id}, 固件 {identity.firmware_version}", flush=True
        )
        print("独立实板演示: 测试数据, 不代表 ARMI 当前心情。Ctrl+C 停止。", flush=True)
        try:
            for cycle in range(args.cycles):
                for face in faces:
                    print(
                        f"[{cycle + 1}/{args.cycles}] {face.label} {face.expression} "
                        f"颜色 {face.color} 活跃度 {args.energy}",
                        flush=True,
                    )
                    until = time.monotonic() + args.seconds
                    while True:
                        apply_face(port, face, args.energy)
                        remaining = until - time.monotonic()
                        if remaining <= 0:
                            break
                        time.sleep(min(8.0, remaining))
                        if time.monotonic() >= until:
                            break
        except KeyboardInterrupt:
            print("已停止轮播。", flush=True)
        apply_face(port, next(face for face in FACES if face.key == "offline"), 0)
        print("演示结束, 已显示离线颜文字并释放串口。", flush=True)


if __name__ == "__main__":
    main()
