#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PCL 2.14.0.0 去更新补丁工具
==========================

用途：把 Plain Craft Launcher 2 正式版 2.14.0.0 (411) 的「启动器自我更新」能力整段切掉，
      其余功能（含全部下载功能）不做任何改动。

原理：
    1. 解析 PE → CLR 头 → ECMA-335 元数据（#~ 表流 / #Strings / #Blob / #US 堆），
       还原 TypeDef / MethodDef，定位 PCL.ModSecret 里的四个更新方法。
    2. 把 UpdateStart / UpdateRestart / UpdateReplace 的 fat 方法头改写为 tiny 方法头
       （code size = 1），方法体只有一条 0x2A (ret)，异常表自动失效，旧 IL 变成不可达数据。
    3. UpdateCheckByButton 改写为 13 字节 IL 桩：ldstr / ldc.i4.0 / ldc.i4.1 /
       call ModMain.Hint(string, HintType, bool) / ret。
    4. #US 堆里「正在检查更新，请稍候！」（11 个 UTF-16 码元）等长替换为
       「本版本已移除更新功能。」——长度前缀不变，堆布局与所有 token 保持有效。

    整个过程不改文件大小、不新增节、不移动任何 RVA、不触碰 .rsrc（WPF 资源）与 .reloc。

限制：仅接受 SHA256 为下列值的原版文件。其他版本偏移不同，脚本会直接拒绝。

用法：
    python patch-pcl-update.py <原版 exe> <输出 exe>
"""

import hashlib
import os
import struct
import sys

EXPECT_SHA256 = "5582952ded3b443503f66c23b810802bd20f1a3e847b54d9e09653a825859a36"

OLD_TEXT = "正在检查更新，请稍候！"
NEW_TEXT = "本版本已移除更新功能。"

TARGET_VOID = ("UpdateStart", "UpdateRestart", "UpdateReplace")
TARGET_HINT = "UpdateCheckByButton"


class PE:
    def __init__(self, data):
        self.d = bytearray(data)
        d = self.d
        e = struct.unpack("<I", d[0x3c:0x40])[0]
        if d[e:e+4] != b"PE\0\0":
            raise ValueError("not a PE file")
        self.e_lfanew = e
        nsec = struct.unpack("<H", d[e+6:e+8])[0]
        opt_size = struct.unpack("<H", d[e+20:e+22])[0]
        self.sections = []
        off = e + 24 + opt_size
        for i in range(nsec):
            b = d[off+i*40: off+(i+1)*40]
            vs, va, rs, rp = struct.unpack("<IIII", b[8:24])
            self.sections.append((va, max(vs, rs), rp))

        dd = e + 24 + (96 if struct.unpack("<H", d[e+24:e+26])[0] == 0x10b else 112)
        clr_rva = struct.unpack("<I", d[dd+14*8:dd+14*8+4])[0]
        clr = self.r2o(clr_rva)
        self.md_rva, self.md_len = struct.unpack("<II", d[clr+8:clr+16])
        self.md_off = self.r2o(self.md_rva)
        self.md = bytes(d[self.md_off:self.md_off+self.md_len])
        self._parse_streams()

    def r2o(self, rva):
        for va, vs, rp in self.sections:
            if va <= rva < va + vs:
                return rp + (rva - va)
        raise ValueError("rva 0x%x not mapped" % rva)

    def _parse_streams(self):
        md = self.md
        verlen = struct.unpack("<I", md[12:16])[0]
        p = 16 + verlen + 2
        n = struct.unpack("<H", md[p:p+2])[0]
        p += 2
        self.streams = {}
        for _ in range(n):
            off, size = struct.unpack("<II", md[p:p+8])
            p += 8
            end = md.index(b"\0", p)
            name = md[p:end].decode()
            p += (len(name)//4 + 1) * 4
            self.streams[name] = (off, size)

    def stream(self, name):
        o, s = self.streams[name]
        return self.md[o:o+s]


class Metadata:
    def __init__(self, pe):
        self.pe = pe
        tbl = pe.stream("#~")
        self.TBL = tbl
        self.STR = pe.stream("#Strings")
        self.BLB = pe.stream("#Blob")
        self.US = pe.stream("#US")

        self.heap_sizes = tbl[6]
        self.S = 4 if self.heap_sizes & 1 else 2
        self.G = 4 if self.heap_sizes & 2 else 2
        self.B = 4 if self.heap_sizes & 4 else 2

        valid = struct.unpack("<Q", tbl[8:16])[0]
        q = 24
        self.rows = {}
        i = 0
        m = valid
        while m:
            if m & 1:
                self.rows[i] = struct.unpack("<I", tbl[q:q+4])[0]
                q += 4
            m >>= 1
            i += 1
        self._compute_offsets(q)

    def _compute_offsets(self, base):
        r = self.rows

        def idx_size(t):
            return 4 if r.get(t, 0) > 0xFFFF else 2

        def coded_size(ts, tag):
            mx = max(r.get(t, 0) for t in ts)
            return 2 if mx.bit_length() + tag <= 16 else 4

        W = {}
        W[0x00] = 2 + self.S + self.G + self.G + self.G
        W[0x01] = coded_size([0x00, 0x1A, 0x23, 0x01], 2) + self.S + self.S
        W[0x02] = (4 + self.S + self.S + coded_size([0x02, 0x01, 0x1B], 2)
                   + idx_size(0x04) + idx_size(0x06))
        W[0x03] = idx_size(0x04)
        W[0x04] = 2 + self.S + self.B
        W[0x05] = idx_size(0x06)
        W[0x06] = 4 + 2 + 2 + self.S + self.B + idx_size(0x08)
        self.W = W

        offs = {}
        cur = base
        for t in range(0x07):
            if t in r:
                offs[t] = cur
                cur += r[t] * W[t]
        self.offs = offs
        self.td_or_ref = coded_size([0x02, 0x01, 0x1B], 2)
        self.field_idx = idx_size(0x04)
        self.method_idx = idx_size(0x06)

    def rd_str(self, i):
        return self.STR[i:self.STR.index(b"\0", i)].decode("utf-8", "replace")

    def ridx(self, pos, size):
        if size == 2:
            return struct.unpack("<H", self.TBL[pos:pos+2])[0]
        return struct.unpack("<I", self.TBL[pos:pos+4])[0]

    def typedefs(self):
        out = []
        p0 = self.offs[0x02]
        for i in range(self.rows.get(0x02, 0)):
            rp = p0 + i * self.W[0x02]
            o = rp + 4
            name = self.rd_str(self.ridx(o, self.S)); o += self.S
            ns = self.rd_str(self.ridx(o, self.S)); o += self.S
            o += self.td_or_ref
            o += self.field_idx
            ml = self.ridx(o, self.method_idx)
            out.append({"ns": ns, "name": name, "methods": ml})
        return out

    def method(self, row):
        rp = self.offs[0x06] + (row - 1) * self.W[0x06]
        rva = struct.unpack("<I", self.TBL[rp:rp+4])[0]
        name = self.rd_str(self.ridx(rp + 8, self.S))
        return {"row": row, "rva": rva, "name": name}


def method_body(pe, rva):
    if rva == 0:
        return None
    o = pe.r2o(rva)
    b0 = pe.d[o]
    if (b0 & 3) == 2:
        return {"tiny": True, "hdr_off": o, "code_off": o + 1, "code_size": b0 >> 2}
    dw = struct.unpack("<H", pe.d[o:o+2])[0]
    hs = (dw >> 12) * 4
    size = struct.unpack("<I", pe.d[o+4:o+8])[0]
    return {"tiny": False, "hdr_off": o, "hdr_size": hs, "code_off": o + hs, "code_size": size}


def to_tiny(pe, body, code):
    """用 tiny 方法头覆盖 fat 头，code 为要执行的指令字节（默认单条 ret）"""
    hdr = bytes([(len(code) << 2) | 0x02])
    pe.d[body["hdr_off"]: body["hdr_off"] + 1 + len(code)] = hdr + code


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, dst = sys.argv[1], sys.argv[2]
    raw = open(src, "rb").read()
    got = hashlib.sha256(raw).hexdigest()
    if got != EXPECT_SHA256:
        print("拒绝执行：输入文件的 SHA256 与目标版本不符。")
        print("  期望: %s" % EXPECT_SHA256)
        print("  实际: %s" % got)
        return 2

    pe = PE(raw)
    md = Metadata(pe)

    # --- 找 PCL.ModSecret ---
    tds = md.typedefs()
    target = None
    for i, td in enumerate(tds):
        if td["ns"] == "PCL" and td["name"] == "ModSecret":
            end = tds[i + 1]["methods"] if i + 1 < len(tds) else md.rows[0x06] + 1
            target = (td["methods"], end)
            break
    if not target:
        print("未找到类型 PCL.ModSecret")
        return 3

    methods = {}
    for row in range(target[0], target[1]):
        m = md.method(row)
        methods[m["name"]] = m

    for name in TARGET_VOID + (TARGET_HINT,):
        if name not in methods:
            print("未找到方法 ModSecret::%s" % name)
            return 4

    # --- 字符串等长替换 ---
    us = pe.stream("#US")
    old_bytes = OLD_TEXT.encode("utf-16-le")
    new_bytes = NEW_TEXT.encode("utf-16-le")
    assert len(old_bytes) == len(new_bytes), "替换文案必须等长"
    pos = us.find(old_bytes)
    if pos < 0:
        print("未在 #US 堆找到目标字符串（可能已打过补丁）")
        return 5
    us_off = pe.streams["#US"][0]
    us_pos = pos                      # #US 堆内偏移，也是 ldstr token 的低 24 位
    file_pos = pe.md_off + us_off + pos
    pe.d[file_pos: file_pos + len(new_bytes)] = new_bytes

    # --- 提取 Hint 调用桩所需的 token ---
    b = method_body(pe, methods[TARGET_HINT]["rva"])
    code = pe.d[b["code_off"]: b["code_off"] + b["code_size"]]
    pat = b"\x72"  # ldstr
    ldstr_tok = call_tok = None
    i = 0
    while i < len(code) - 10:
        if code[i] == 0x72 and code[i+5] in (0x16, 0x17) and code[i+6] in (0x16, 0x17) and code[i+7] == 0x28:
            ldstr_tok = struct.unpack("<I", code[i+1:i+5])[0]
            call_tok = struct.unpack("<I", code[i+8:i+12])[0]
            break
        i += 1
    if ldstr_tok is None:
        print("未能在 UpdateCheckByButton 中定位 Hint 调用模式")
        return 6

    # 确认该 ldstr 指向的就是要替换的字符串
    # ldstr token 指向 #US 里的长度前缀字节，长度前缀通常 1 字节，故数据起点 = 低24位 + 1
    if (ldstr_tok & 0xFFFFFF) + 1 != us_pos:
        print("ldstr token 与字符串位置不匹配：0x%08x vs 0x%x" % (ldstr_tok, us_pos))
        return 7

    # --- 打补丁 ---
    for name in TARGET_VOID:
        body = method_body(pe, methods[name]["rva"])
        if body["tiny"]:
            print("%s 已是 tiny 方法体，跳过" % name)
            continue
        to_tiny(pe, body, b"\x2a")
        print("%-22s @0x%06x -> ret" % (name, body["hdr_off"]))

    hint_code = (b"\x72" + struct.pack("<I", ldstr_tok) +
                 b"\x16\x17" +
                 b"\x28" + struct.pack("<I", call_tok) +
                 b"\x2a")
    assert len(hint_code) == 13
    body = method_body(pe, methods[TARGET_HINT]["rva"])
    to_tiny(pe, body, hint_code)
    print("%-22s @0x%06x -> Hint(\"%s\") + ret" % (TARGET_HINT, body["hdr_off"], NEW_TEXT))
    print("字符串                 -> \"%s\" (%d 字节)" % (NEW_TEXT, len(new_bytes)))

    out = bytes(pe.d)
    assert len(out) == len(raw), "输出大小必须与原文件一致"
    open(dst, "wb").write(out)
    print("\n完成：%s" % dst)
    print("SHA256: %s" % hashlib.sha256(out).hexdigest())
    return 0


if __name__ == "__main__":
    sys.exit(main())
