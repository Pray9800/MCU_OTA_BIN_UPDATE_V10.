# -*- coding: utf-8 -*-
"""验证 merged.hex 是否等于 bootloader.hex + app.hex 的正确拼接"""
import sys

def load_lines(path):
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return [l.strip() for l in f if l.strip()]

def parse_line(line):
    raw = bytes.fromhex(line[1:])
    return raw[0], (raw[1] << 8) | raw[2], raw[3], raw[4:]

def addr_ranges(lines, label):
    base = 0
    segs = []
    for l in lines:
        bc, a, rt, d = parse_line(l)
        if rt == 0x04:
            base = ((d[0] << 8) | d[1]) << 16
        elif rt == 0x00:
            segs.append((base + a, base + a + bc))
    if segs:
        print(f"{label}: 0x{min(s[0] for s in segs):08X} ~ 0x{max(s[1] for s in segs):08X}, {len(segs)} 数据行")
    return segs

def main(boot_path, app_path, merged_path):
    boot = load_lines(boot_path)
    app = load_lines(app_path)
    merged = load_lines(merged_path)

    print(f"行数: boot={len(boot)}, app={len(app)}, merged={len(merged)}")

    # 1. EOF 记录数量
    eof_count = sum(1 for l in merged if l == ":00000001FF")
    print(f"\n[1] EOF记录数: {eof_count}", "-> OK (应为1)" if eof_count == 1 else "-> FAIL (应为1)")

    # 2. 期望拼接 = boot去EOF + app
    boot_trim = list(boot)
    while boot_trim and boot_trim[-1] == ":00000001FF":
        boot_trim.pop()
    expect = boot_trim + app
    if expect == merged:
        print("[2] 逐行对比: merged == boot(去EOF) + app -> OK")
    else:
        print("[2] 逐行对比: FAIL")
        for i, (a, b) in enumerate(zip(expect, merged)):
            if a != b:
                print(f"    第{i}行不一致:\n      期望: {a}\n      实际: {b}")
                break
        if len(expect) != len(merged):
            print(f"    行数不等: 期望{len(expect)} vs 实际{len(merged)}")

    # 3. 地址范围与重叠
    boot_segs = addr_ranges(boot, "boot范围")
    app_segs = addr_ranges(app, "app范围")
    merged_segs = addr_ranges(merged, "merged范围")

    overlap = any(a1 < b2 and a2 < b1 for a1, b1 in boot_segs for a2, b2 in app_segs)
    print(f"\n[3] 地址重叠: {'有! FAIL' if overlap else '无 OK'}")

    # 4. 分区边界
    boot_min, boot_max = min(s[0] for s in boot_segs), max(s[1] for s in boot_segs)
    app_min, app_max = min(s[0] for s in app_segs), max(s[1] for s in app_segs)
    checks = [
        (boot_min >= 0x08000000 and boot_max <= 0x08008000, f"Bootloader在[0x08000000,0x08008000)内: 0x{boot_min:08X}~0x{boot_max:08X}"),
        (app_min >= 0x08008000 and app_max <= 0x08044000, f"APP在[0x08008000,0x08044000)内: 0x{app_min:08X}~0x{app_max:08X}"),
    ]
    print("\n[4] 分区边界:")
    for ok, desc in checks:
        print(f"    {'OK' if ok else 'FAIL'} - {desc}")

    # 5. 每行校验和
    bad = 0
    for i, l in enumerate(merged):
        raw = bytes.fromhex(l[1:])
        if sum(raw) & 0xFF != 0:
            print(f"    校验和错误 第{i}行: {l}")
            bad += 1
    print(f"\n[5] 行校验和: {'全部OK' if bad == 0 else f'{bad}行错误'}")

if __name__ == "__main__":
    base = r"E:\JT-004\JT004-ROBOTCART-STM32-V1.0\OTA_BIN_UPDATE\merge_cmd"
    import os
    if not os.path.isdir(base):
        base = os.path.dirname(os.path.abspath(__file__))
    main(os.path.join(base, "JT004_ROBOT_Bootloader.hex"),
         os.path.join(base, "JT004-ROBOTCART-STM32-V1.0.hex"),
         os.path.join(base, "merged.hex"))
