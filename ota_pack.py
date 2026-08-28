# -*- coding: utf-8 -*-
#V1.0 适用于加前面十六字节
"""
JT004 OTA 固件打包脚本 (M1)
用法:
    python ota_pack.py <输入.bin> [-v 版本号] [-o 输出.bin]

示例:
    python ota_pack.py JT004-ROBOTCART-STM32-V1.0.bin -v 0x0102 -o upgrade.bin

打包格式 = 16字节包头 + bin原文, 与 Bootloader 的 OTA_Header_t (bsp_flash.h,
#pragma pack(1)) 逐字节对齐, 小端:

    offset 0  : magic    4B  "JJST" 
    offset 4  : version  2B  固件版本 (默认 0x0100)
    offset 6  : file_size 4B  bin字节数        ← pack(1)无填充, 紧贴version!
    offset 10 : crc16    2B  Modbus CRC16, 只算bin正文
    offset 12 : reserved 4B  填0
    offset 16 : bin 原文

CRC16 算法与 bsp_crc.c 的 CRC16_Modbus 完全一致:
    多项式 0xA001 (0x8005反转), 初值 0xFFFF, 无异或输出
"""
import argparse
import struct
import sys
import os

MAGIC =  0x54534a4a  # "JJST"
MAX_SIZE = 238 * 1024  # 下载区上限 (0x0807F800 - 0x08044000)


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


# 标准校验向量: CRC-16/MODBUS 对 "123456789" 的公开标准值
SELF_TEST = (b"123456789", 0x4B37)


def run_self_test() -> bool:
    data, expect = SELF_TEST
    got = crc16_modbus(data)
    ok = got == expect
    print(f"  [{'OK' if ok else 'FAIL'}] crc16('123456789') = 0x{got:04X} "
          f"(标准值 0x{expect:04X})")
    return ok


def inspect_package(path: str) -> bool:
    """读取并校验 OTA 包头和固件正文。"""
    try:
        with open(path, "rb") as f:
            package = f.read()
    except OSError as exc:
        print(f"!! 无法读取文件: {exc}")
        return False

    if len(package) < 16:
        print("!! 格式错误: 文件不足16字节，缺少完整包头")
        return False

    magic, version, file_size, stored_crc, reserved = struct.unpack(
        "<IHIHI", package[:16]
    )
    payload = package[16:]

    if magic != MAGIC:
        print(f"!! 格式错误: JT04 magic 不正确 (0x{magic:08X})")
        return False
    if reserved != 0:
        print(f"!! 格式错误: reserved 不为0 (0x{reserved:08X})")
        return False
    if file_size != len(payload):
        print(f"!! 格式错误: 文件长度字段为 {file_size}，实际为 {len(payload)}")
        return False
    if file_size == 0 or file_size > MAX_SIZE:
        print(f"!! 格式错误: 固件大小 {file_size} 超出有效范围")
        return False

    calculated_crc = crc16_modbus(payload)
    if stored_crc != calculated_crc:
        print(f"!! 格式错误: CRC 不匹配 (包内 0x{stored_crc:04X}, "
              f"计算值 0x{calculated_crc:04X})")
        return False

    magic_ascii = struct.pack("<I", magic).decode("ascii")
    print(f"文件   : {path}")
    print(f"JJST   : {magic_ascii}")
    print(f"版本   : 0x{version:04X}")
    print(f"大小   : {file_size} 字节")
    print(f"CRC16  : 0x{stored_crc:04X}")
    print("格式校验: [OK]")
    return True


def main():
    parser = argparse.ArgumentParser(description="JT004 OTA 打包工具")
    parser.add_argument("input", help="输入 bin 文件 (编译产物)")
    parser.add_argument("-v", "--version", default="0x0100",
                        help="固件版本 (hex 如 0x0102, 默认 0x0100)")
    parser.add_argument("-o", "--output", default="upgrade.bin",
                        help="输出文件名 (默认 upgrade.bin)")
    parser.add_argument("--inspect", action="store_true",
                        help="读取并校验 OTA 包信息，不执行打包")
    args = parser.parse_args()

    print("== JT004 OTA 打包工具 ==")

    print("CRC16 自测:")
    if not run_self_test():
        print("!! CRC16 实现与标准不符, 中止。")
        sys.exit(1)

    if (not args.inspect and os.path.abspath(args.input) ==
            os.path.abspath(args.output) and os.path.isfile(args.input)):
        print("检测到输入文件与输出文件相同，自动读取 OTA 包信息:")
        sys.exit(0 if inspect_package(args.input) else 1)

    if args.inspect:
        sys.exit(0 if inspect_package(args.input) else 1)

    if not os.path.isfile(args.input):
        print(f"!! 找不到输入文件: {args.input}")
        sys.exit(1)

    with open(args.input, "rb") as f:
        bin_data = f.read()

    version = int(args.version, 16) & 0xFFFF

    size = len(bin_data)
    if size == 0:
        print("!! 输入文件为空")
        sys.exit(1)
    if size > MAX_SIZE:
        print(f"!! 固件 {size} 字节超过下载区上限 {MAX_SIZE} 字节")
        sys.exit(1)

    # ---- 镜像体检: 复位向量必须落在 APP 区, 否则拒绝打包 ----
    # 2026-08-26 台车事故根因: 误把按 0x08000000 链接的标准版固件打包进去,
    # 烧入后 Bootloader 跳到 0x08003805 (Bootloader 区中间) 直接死机。
    # 此检查确保这类错误链接的 bin 根本打不出包。
    sp, reset = struct.unpack_from("<II", bin_data, 0)
    APP_BASE, APP_END = 0x08008000, 0x08044000  # APP 区 240KB
    if not (APP_BASE <= reset < APP_END):
        print(f"!! 拒绝打包: 复位向量 0x{reset:08X} 不在 APP 区 [0x08008000, 0x08043FFF]")
        print("   这是按 0x08000000 链接的固件(标准版/CE/Bootloader/旧构建), 烧进去必死机。")
        print("   正确输入: JT004-ROBOTCART-STM32-OTAversion\\build\\Debug\\ 下的 bin")
        sys.exit(1)
    if not (0x20000000 <= sp <= 0x20010000):
        print(f"!! 拒绝打包: 栈顶指针 0x{sp:08X} 不在 64KB RAM 范围内")
        sys.exit(1)
    print(f"镜像体检: 栈顶 0x{sp:08X} / 复位向量 0x{reset:08X} 位于 APP 区 [OK]")

    crc = crc16_modbus(bin_data)

    # 16字节包头: 与 pack(1) 的 OTA_Header_t 逐字节一致
    # I=4B magic, H=2B version, I=4B file_size(偏移6,无填充), H=2B crc16, I=4B reserved
    header = struct.pack("<IHIHI", MAGIC, version, size, crc, 0)
    assert len(header) == 16

    with open(args.output, "wb") as f:
        f.write(header + bin_data)

    print(f"\n输入   : {args.input}  ({size} 字节)")
    print(f"版本   : 0x{version:04X}")
    print(f"CRC16  : 0x{crc:04X}")
    print(f"输出   : {args.output}  ({size + 16} 字节)")
    print(f"\n包头16字节: {header.hex(' ')}")
    print("\n完成。流程: 发 UPDATE_FIRMWARE 暗号 -> 等 READY! -> 网络助手发送此文件。")


if __name__ == "__main__":
    main()
