#!/usr/bin/env python3
"""Static loader for a PSP user-mode module: a relocatable PRX (ELF type 0xFFA0)
or a fixed-address executable (ELF type 2, ET_EXEC, as decrypted EBOOTs often are).

Loads the segments (a PRX at a fixed base), applies PSP relocations (section
type 0x700000A0) exactly like the PSP/PPSSPP loader, and parses sceModuleInfo,
the import stubs (.lib.stub) and exports (.lib.ent). An ET_EXEC has no
relocations: ptr_relocs/code_relocs stay empty and analyze.py finds pointers
by scanning instead.

Everything the recompiler needs about the image comes from here:
  img.mem            bytearray, guest address img.base + i
  img.sections       {name: (addr, size)}  (relocated addresses)
  img.imports        [Import]   one per stub (8 bytes each)
  img.ptr_relocs     {addr: target}  32-bit pointers written by R_MIPS_32
  img.code_relocs    {addr: (type, target)}  hi/lo/26 relocations in code
"""
import json, struct, pathlib
from dataclasses import dataclass

BASE = 0x08804000
SHT_PRX_RELOC = 0x700000A0
R_NONE, R_16, R_32, R_REL32, R_26, R_HI16, R_LO16, R_GPREL16 = range(8)


@dataclass
class Import:
    lib: str
    nid: int
    stub: int          # guest address of the 8-byte stub
    name: str          # resolved name or "<lib>_<NID>"
    ret: str = ""
    args: str = ""


@dataclass
class Export:
    lib: str
    nid: int
    addr: int


class Image:
    def __init__(self, path, base=BASE, nid_db=None):
        self.path = path
        self.base = base
        raw = pathlib.Path(path).read_bytes()
        self.raw = raw
        (e_type, e_machine, _, e_entry, e_phoff, e_shoff, _, _, e_phentsize, e_phnum,
         e_shentsize, e_shnum, e_shstrndx) = struct.unpack_from("<HHIIIIIHHHHHH", raw, 16)
        assert raw[:4] == b"\x7fELF" and e_type in (0xFFA0, 2, 0xFFA8), "not a PSP module"
        self.is_overlay = e_type == 0xFFA8     # Chinatown Wars code overlay: fixed address, no module info
        self.is_exec = e_type == 2 or self.is_overlay

        self.phdrs = [struct.unpack_from("<8I", raw, e_phoff + i * e_phentsize) for i in range(e_phnum)]
        if self.is_exec:
            # Absolute addresses: express them relative to the lowest segment, like a PRX.
            base = self.base = min(p[2] for p in self.phdrs if p[0] == 1)
            self.phdrs = [(p[0], p[1], p[2] - base) + tuple(p[3:]) for p in self.phdrs]
            e_entry -= base
        self.shdrs = [struct.unpack_from("<10I", raw, e_shoff + i * e_shentsize) for i in range(e_shnum)]
        strtab = self.shdrs[e_shstrndx]
        def secname(off):
            s = raw[strtab[4] + off:]
            return s[:s.index(0)].decode()

        # Segments: memsz of all PT_LOADs, laid out contiguously from base.
        self.seg_vaddr = [base + p[2] for p in self.phdrs]
        top = max(p[2] + p[5] for p in self.phdrs)
        self.size = (top + 0xFF) & ~0xFF
        self.mem = bytearray(self.size)
        for p in self.phdrs:
            _, off, vaddr, paddr, filesz, memsz, flags, align = p
            self.mem[vaddr:vaddr + filesz] = raw[off:off + filesz]
        self.entry = base + e_entry
        # seg0 p_paddr holds the *file offset* of sceModuleInfo
        p0 = self.phdrs[0]
        self.modinfo_addr = base + p0[2] + p0[3] - p0[1]

        self.sections = {}
        self.section_list = []
        for sh in self.shdrs:
            name = secname(sh[0])
            if sh[2] & 2:  # SHF_ALLOC
                addr = sh[3] if self.is_exec else base + sh[3]
                self.sections.setdefault(name, (addr, sh[5]))
                self.section_list.append((name, addr, sh[5], sh[2]))
        self.section_list.sort(key=lambda s: s[1])
        if self.is_overlay:
            self._split_overlay()

        self.ptr_relocs, self.code_relocs = {}, {}
        self.reloc_stats = {}
        for sh in self.shdrs:
            if sh[1] == SHT_PRX_RELOC:
                self._apply_relocs(raw[sh[4]:sh[4] + sh[5]])

        self.scanned = False
        if self.is_exec:
            self._scan_pointers()

        self.nid_db = nid_db or {}
        if self.is_overlay:
            self.mod_name, self.gp, self.imports, self.exports = self.overlay_name, 0, [], []
            return
        self._parse_modinfo()
        self._parse_imports()
        self._parse_exports()

    def _split_overlay(self):
        """An overlay is one WAX section: a 16-byte header, then the code, rodata and data
        of its object files, interleaved. All of it after the header is called .text; the
        analyzer finds the code by tracing, and the pointer scan reads every word."""
        name, a, n, fl = self.section_list[0]
        self.overlay_name = name.removeprefix(".overlay_")
        self.overlay_header = [self.u32(a + 4 * i) for i in range(4)]
        self.section_list = [(".ovhdr", a, 16, 2), (".text", a + 16, n - 16, 7)]
        self.sections = {s[0]: (s[1], s[2]) for s in self.section_list}
        # header: [id, init function, ?, ?]; the loader calls the init function after loading
        hdr_code = [p for p in self.overlay_header[1:] if a + 16 <= p < a + n and not p & 3]
        self.entry = hdr_code[0] if hdr_code else a + 16
        self.header_pointers = hdr_code

    # --- memory helpers -------------------------------------------------
    def u32(self, a):
        return struct.unpack_from("<I", self.mem, a - self.base)[0]

    def u16(self, a):
        return struct.unpack_from("<H", self.mem, a - self.base)[0]

    def u8(self, a):
        return self.mem[a - self.base]

    def cstr(self, a):
        o = a - self.base
        return self.mem[o:self.mem.index(0, o)].decode("latin-1")

    def contains(self, a):
        return self.base <= a < self.base + self.size

    def section_of(self, a):
        for name, s, n, _ in self.section_list:
            if s <= a < s + n:
                return name
        return None

    # --- pointer scan (ET_EXEC: no relocations) ---------------------------
    def _scan_pointers(self):
        """Rebuild what relocations would have told us: jal targets (R_26), lui/lo
        address pairs (R_HI16 at the lui, full address) and 32-bit words in data
        that point into the image (R_32). Data words are only candidates; the
        analyzer decides which code pointers are real function starts."""
        self.scanned = True
        self.code_relocs, self.ptr_relocs = self.scan_refs(self.base, self.base + self.size)

    def scan_refs(self, lo, hi):
        """jal targets, lui/lo address pairs and data words of this image that point into [lo, hi)."""
        code_relocs, ptr_relocs = {}, {}
        code = [(a, n) for name, a, n, fl in self.section_list if fl & 4]   # SHF_EXECINSTR
        LO_OPS = {9, 13, 32, 33, 35, 36, 37, 40, 41, 43, 49, 57, 53, 61}    # addiu ori lb lh lw lbu lhu sb sh sw lwc1 swc1 lv.s sv.s
        for start, n in code:
            for a in range(start, start + n, 4):
                w = self.u32(a)
                op = w >> 26
                if op == 3:   # jal
                    t = ((a + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
                    if lo <= t < hi:
                        code_relocs[a] = (R_26, t)
                elif op == 15:   # lui rt, imm: find the first use of rt as a base/source
                    rt = (w >> 16) & 31
                    upper = (w & 0xFFFF) << 16
                    for b in range(a + 4, min(a + 4 + 4 * 24, start + n), 4):
                        u = self.u32(b)
                        uop = u >> 26
                        if uop in LO_OPS and ((u >> 21) & 31) == rt:
                            imm = u & 0xFFFF
                            if uop == 13:
                                full = upper | imm
                            else:
                                full = (upper + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF
                            if lo <= full < hi:
                                code_relocs[a] = (R_HI16, full)
                            break
                        # rt overwritten (I-type rt / R-type rd) or control flow leaves: give up
                        if (uop in (8, 9, 10, 11, 12, 13, 14, 15, 32, 33, 35, 36, 37) and ((u >> 16) & 31) == rt) or \
                           (uop == 0 and ((u >> 11) & 31) == rt) or uop in (2, 3) or (uop == 0 and (u & 0x3F) in (8, 9)):
                            break
        for name, a, n, fl in self.section_list:
            if (fl & 4 and not self.is_overlay) or not (fl & 2) or \
                    name.startswith((".lib.", ".rodata.sceNid", ".rodata.sceModuleInfo")):
                continue
            for p in range((a + 3) & ~3, a + n - 3, 4):
                v = self.u32(p)
                if lo <= v < hi:
                    ptr_relocs[p] = v
        return code_relocs, ptr_relocs

    # --- relocations ----------------------------------------------------
    def _apply_relocs(self, data):
        rels = [struct.unpack_from("<II", data, i) for i in range(0, len(data) - 7, 8)]
        segv = self.seg_vaddr
        addrs, ops = [], []
        for off, info in rels:
            rw = (info >> 8) & 0xFF
            a = off + segv[rw] if rw < len(segv) else None
            addrs.append(a)
            ops.append(self.u32(a) if a is not None and a + 4 <= self.base + self.size else 0)

        for r, (off, info) in enumerate(rels):
            t = info & 0xF
            rel = (info >> 16) & 0xFF
            a = addrs[r]
            self.reloc_stats[t] = self.reloc_stats.get(t, 0) + 1
            if a is None or ((a & 3) and t != R_32):
                continue
            to = segv[rel] if rel < len(segv) else 0
            op = ops[r]
            if t == R_32:
                op = (op + to) & 0xFFFFFFFF
                self.ptr_relocs[a] = op
            elif t == R_26:
                op = (op & 0xFC000000) | (((op & 0x03FFFFFF) + (to >> 2)) & 0x03FFFFFF)
                self.code_relocs[a] = (t, ((a + 4) & 0xF0000000) | ((op & 0x03FFFFFF) << 2))
            elif t == R_HI16:
                cur = (op & 0xFFFF) << 16
                for q in range(r + 1, len(rels)):
                    qt = rels[q][1] & 0xF
                    if qt == R_HI16:
                        continue
                    if qt not in (R_LO16, R_16):
                        continue
                    lo = ops[q] & 0xFFFF
                    lo = lo - 0x10000 if lo & 0x8000 else lo
                    full = (cur + lo + to) & 0xFFFFFFFF
                    hi = ((full + 0x8000) >> 16) & 0xFFFF
                    op = (op & 0xFFFF0000) | hi
                    self.code_relocs[a] = (t, full)
                    break
            elif t == R_LO16:
                op = (op & 0xFFFF0000) | (((op & 0xFFFF) + to) & 0xFFFF)
                self.code_relocs[a] = (t, None)
            elif t == R_16:
                op = (op & 0xFFFF0000) | (((op & 0xFFFF) + to) & 0xFFFF)
            else:
                continue
            struct.pack_into("<I", self.mem, a - self.base, op)

    # --- module info / imports / exports --------------------------------
    def _parse_modinfo(self):
        a = self.modinfo_addr
        self.mod_attr, self.mod_ver = self.u16(a), self.u16(a + 2)
        self.mod_name = self.cstr(a + 4)
        self.gp, self.libent, self.libent_end, self.libstub, self.libstub_end = (
            self.u32(a + 32 + 4 * i) for i in range(5))

    def _parse_imports(self):
        self.imports = []
        a = self.libstub
        while a < self.libstub_end:
            name_p = self.u32(a)
            size = self.u8(a + 8)
            nvars, nfuncs = self.u8(a + 9), self.u16(a + 10)
            nids_p, stubs_p = self.u32(a + 12), self.u32(a + 16)
            lib = self.cstr(name_p) if name_p else "?"
            known = self.nid_db.get(lib, {})
            for i in range(nfuncs):
                nid = self.u32(nids_p + 4 * i)
                info = known.get(f"0x{nid:08X}")
                self.imports.append(Import(
                    lib, nid, stubs_p + 8 * i,
                    info["name"] if info else f"{lib}_{nid:08X}",
                    info["ret"] if info else "", info["args"] if info else ""))
            a += size * 4

    def _parse_exports(self):
        self.exports = []
        a = self.libent
        while a < self.libent_end:
            name_p = self.u32(a)
            size = self.u8(a + 8)
            nvars, nfuncs = self.u8(a + 9), self.u16(a + 10)
            tab = self.u32(a + 12)
            lib = self.cstr(name_p) if name_p else "syslib"
            n = nvars + nfuncs
            for i in range(n):
                self.exports.append(Export(lib, self.u32(tab + 4 * i), self.u32(tab + 4 * (n + i))))
            a += size * 4


def load(path, nid_path=None, base=BASE):
    db = json.load(open(nid_path)) if nid_path else None
    return Image(path, base, db)


if __name__ == "__main__":
    import sys
    root = pathlib.Path(__file__).resolve().parent.parent
    img = load(sys.argv[1], root / "data" / "nids.json")
    print(f"module '{img.mod_name}' attr={img.mod_attr:#x} ver={img.mod_ver:#x}")
    print(f"base={img.base:#x} size={img.size:#x} entry={img.entry:#x} gp={img.gp:#x}")
    print("reloc types:", {k: v for k, v in sorted(img.reloc_stats.items())})
    print(f"{len(img.ptr_relocs)} pointer relocs, {len(img.code_relocs)} code relocs")
    print("exports:")
    for e in img.exports:
        print(f"  {e.lib} {e.nid:08X} -> {e.addr:#x}")
    unknown = [i for i in img.imports if i.name.startswith(i.lib + "_")]
    print(f"imports: {len(img.imports)} ({len(unknown)} unresolved)")
    for i in img.imports:
        print(f"  {i.stub:#010x} {i.lib:24s} {i.nid:08X} {i.name}")
