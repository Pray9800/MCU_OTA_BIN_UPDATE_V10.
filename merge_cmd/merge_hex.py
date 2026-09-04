# -*- coding: utf-8 -*-
"""
JT004 HEX 合并工具
将 Bootloader HEX 和 APP HEX 合并为一个文件，用于初始烧录。

用法:
    python merge_hex.py [-b bootloader.hex] [-a app.hex] [-o output.hex]

默认路径:
    Bootloader: ..\JT004_ROBOT_Bootloader\build\Debug\JT004_ROBOT_Bootloader.hex
    APP:        ..\JT004-ROBOTCART-STM32-OTAversion\build\Debug\JT004-ROBOTCART-STM32-V1.0.hex
    输出:       merged.hex

合并原理:
    Intel HEX 格式每条记录自带地址，两个HEX文件的地址不重叠
    (Bootloader: 0x08000000~0x08007FFF, APP: 0x08008000~0x08043FFF)
    只需去掉中间的 EOF 记录，保留最后一个即可。
"""
import argparse
import os
import sys

DEFAULT_BOOT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "JT004_ROBOT_Bootloader", "build", "Debug", "JT004_ROBOT_Bootloader.hex"
)
DEFAULT_APP = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "..", "JT004-ROBOTCART-STM32-OTAversion", "build", "Debug", "JT004-ROBOTCART-STM32-V1.0.hex"
)
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "merged.hex")

BOOT_BASE = 0x08000000
BOOT_END  = 0x08008000
APP_BASE  = 0x08008000
APP_END   = 0x08044000


def parse_hex_line(line):
    """解析一行 Intel HEX 记录，返回 (byte_count, addr, rectype, data_str)。"""
    line = line.strip()
    if not line.startswith(":"):
        return None
    raw = bytes.fromhex(line[1:])
    byte_count = raw[0]
    addr = (raw[1] << 8) | raw[2]
    rectype = raw[3]
    data = raw[4:4 + byte_count]
    return byte_count, addr, rectype, data


def get_hex_ranges(filepath):
    """扫描 HEX 文件，返回数据记录的地址范围列表 [(start, end), ...]。"""
    base_addr = 0
    ranges = []
    with open(filepath, "r") as f:
        for line in f:
            parsed = parse_hex_line(line)
            if parsed is None:
                continue
            byte_count, addr, rectype, data = parsed
            if rectype == 0x04:
                base_addr = (data[0] << 8 | data[1]) << 16
            elif rectype == 0x00:
                full_addr = base_addr + addr
                ranges.append((full_addr, full_addr + byte_count))
    return ranges


def merge_hex(boot_path, app_path, out_path):
    if not os.path.isfile(boot_path):
        print(f"!! 找不到 Bootloader HEX: {boot_path}")
        sys.exit(1)
    if not os.path.isfile(app_path):
        print(f"!! 找不到 APP HEX: {app_path}")
        sys.exit(1)

    print("== JT004 HEX 合并工具 ==\n")

    # 检查地址范围
    boot_ranges = get_hex_ranges(boot_path)
    app_ranges = get_hex_ranges(app_path)

    if boot_ranges:
        boot_min = min(r[0] for r in boot_ranges)
        boot_max = max(r[1] for r in boot_ranges)
        print(f"Bootloader: {os.path.basename(boot_path)}")
        print(f"  地址范围: 0x{boot_min:08X} ~ 0x{boot_max:08X} ({boot_max - boot_min} 字节)")
        if boot_min < BOOT_BASE or boot_max > BOOT_END:
            print(f"  !! 警告: Bootloader 地址超出预期 [0x{BOOT_BASE:08X}, 0x{BOOT_END:08X})")
    else:
        print("!! Bootloader HEX 无数据记录")
        sys.exit(1)

    if app_ranges:
        app_min = min(r[0] for r in app_ranges)
        app_max = max(r[1] for r in app_ranges)
        print(f"APP:        {os.path.basename(app_path)}")
        print(f"  地址范围: 0x{app_min:08X} ~ 0x{app_max:08X} ({app_max - app_min} 字节)")
        if app_min < APP_BASE or app_max > APP_END:
            print(f"  !! 警告: APP 地址超出预期 [0x{APP_BASE:08X}, 0x{APP_END:08X})")
    else:
        print("!! APP HEX 无数据记录")
        sys.exit(1)

    # 检查重叠
    if boot_max > app_min:
        print(f"\n!! 错误: Bootloader 和 APP 地址重叠 (0x{boot_max:08X} > 0x{app_min:08X})")
        sys.exit(1)

    print(f"\n地址无重叠，开始合并...")

    # 合并: 读 Bootloader 全部行（去掉末尾EOF），再追加 APP 全部行（保留末尾EOF）
    with open(boot_path, "r") as f:
        boot_lines = [l.strip() for l in f if l.strip()]
    with open(app_path, "r") as f:
        app_lines = [l.strip() for l in f if l.strip()]

    # 去掉 Bootloader 末尾的 EOF 记录 (:00000001FF)
    while boot_lines and boot_lines[-1] == ":00000001FF":
        boot_lines.pop()

    merged = boot_lines + app_lines

    with open(out_path, "w") as f:
        for line in merged:
            f.write(line + "\n")

    total_bytes = (boot_max - boot_min) + (app_max - app_min)
    print(f"\n输出: {out_path}")
    print(f"  Bootloader: {boot_max - boot_min} 字节")
    print(f"  APP:        {app_max - app_min} 字节")
    print(f"  合计:       {total_bytes} 字节")
    print(f"  行数:       {len(merged)}")
    print(f"\n完成。用烧录器一次性烧入 merged.hex 即可。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JT004 HEX 合并工具")
    parser.add_argument("-b", "--boot", default=DEFAULT_BOOT,
                        help="Bootloader HEX 路径")
    parser.add_argument("-a", "--app", default=DEFAULT_APP,
                        help="APP HEX 路径")
    parser.add_argument("-o", "--output", default=DEFAULT_OUT,
                        help="合并输出 HEX 路径")
    args = parser.parse_args()

    merge_hex(args.boot, args.app, args.output)
