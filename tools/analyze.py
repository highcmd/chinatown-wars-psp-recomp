#!/usr/bin/env python3
"""Function discovery for the loaded PRX.

Seeds:   module entry/exports, every jal target, code pointers stored in data
         (.data/.linkonce.d/.cplinit/.ctors: vtables, callbacks, static ctors),
         code addresses materialised with lui/addiu (HI16/LO16 relocs).
Bodies:  a function runs from its seed to the next seed; we trace its control
         flow to find the real end, resolve jump tables at `jr <reg>`, and turn
         any non-padding code left after the end into a new (orphan) function.
Output:  data/functions.json  {functions: [...], jumptables: {...}, stats}
"""
import bisect, json, sys, pathlib
import psp_prx

ROOT = pathlib.Path(__file__).resolve().parent.parent

OP_J, OP_JAL = 2, 3
BRANCH_OPS = {1, 4, 5, 6, 7, 20, 21, 22, 23}       # regimm, beq, bne, blez, bgtz, +likely
COP_BRANCH = {(17, 8), (18, 3)}                    # bc1x, bvx (VFPU branch is cop2 rs=8)


def branch_target(w, a):
    """Return target for a conditional branch word, else None."""
    op = w >> 26
    off = w & 0xFFFF
    off = off - 0x10000 if off & 0x8000 else off
    tgt = (a + 4 + (off << 2)) & 0xFFFFFFFF
    if op in BRANCH_OPS:
        if op == 1 and ((w >> 16) & 0x1F) not in (0, 1, 2, 3, 16, 17, 18, 19):
            return None
        return tgt
    if op == 17 and ((w >> 21) & 0x1F) == 8:   # bc1f/t/fl/tl
        return tgt
    if op == 18 and ((w >> 21) & 0x1F) == 8:   # bvf/bvt/bvfl/bvtl
        return tgt
    return None


def is_uncond_branch(w):
    op = w >> 26
    # beq $0,$0 (b) or bgez $0 / bal
    return (op == 4 and ((w >> 21) & 31) == 0 and ((w >> 16) & 31) == 0) or \
           (op == 1 and ((w >> 21) & 31) == 0 and ((w >> 16) & 31) in (1, 17))


class Analyzer:
    def __init__(self, img, extra_seeds=(), stub_range=None):
        self.img = img
        self.extra_seeds = extra_seeds   # addresses referenced from other images (main <-> overlays)
        self.code_ranges = [img.sections[s] for s in (".text", "render_model") if s in img.sections]
        if stub_range:
            self.stub_lo, self.stub_hi = stub_range
        else:
            stubs = [img.sections[n] for n in img.sections if n.startswith(".sceStub.text")]
            self.stub_lo = min(s for s, _ in stubs)
            self.stub_hi = max(s + n for s, n in stubs)
        self.import_at = {i.stub: i for i in img.imports}
        self.jumptables = {}       # jr address -> (table addr, [targets])
        self.notes = []
        self.islands = self.find_code_islands() if img.scanned else []
        self.code_ranges += self.islands
        # Without relocations, jump-table entries look like code pointers: find every
        # table first (independent of function bounds) so they never become seeds.
        self.jt_entries = self.prescan_jumptables() if img.scanned else set()

    def is_code(self, a):
        return any(s <= a < s + n for s, n in self.code_ranges)

    def word(self, a):
        return self.img.u32(a)

    # ------------------------------------------------------------------
    def seeds(self):
        img = self.img
        S = {img.entry: "entry"}
        for a in getattr(img, "header_pointers", ()):   # overlay header: init function etc.
            S.setdefault(a, "entry")
        for a in getattr(self, "island_seeds", ()):
            S[a] = "island"
        for e in img.exports:
            if self.is_code(e.addr):
                S.setdefault(e.addr, "export")
        for a, (t, tgt) in img.code_relocs.items():
            if t == psp_prx.R_26 and (self.word(a) >> 26) == OP_JAL and self.is_code(tgt) and self.is_code(a):
                S.setdefault(tgt, "jal")
        # With real relocations every code pointer is a pointer. Scanned pointers
        # (ET_EXEC) are only numbers that look like addresses: keep the ones that
        # land on something shaped like a function start.
        plausible = self.looks_like_start if img.scanned else (lambda a: True)
        if img.is_overlay:   # zero-filled data next to code is not a function either
            plausible = lambda a, f=plausible: self.word(a) != 0 and f(a)
        jal_targets = set(S)
        for a, tgt in img.ptr_relocs.items():
            if not self.is_code(tgt) or tgt & 3:
                continue
            sec = img.section_of(a)
            if sec in (".data", ".linkonce.d", ".cplinit", ".ctors", ".dtors", ".rodata.sceResident") or \
                    (img.scanned and sec and not sec.startswith(".lib")):
                if tgt in jal_targets or (tgt not in self.jt_entries and plausible(tgt)):
                    S.setdefault(tgt, "dataptr")
        for t in self.extra_seeds:
            if self.is_code(t) and not t & 3 and t not in self.jt_entries and plausible(t):
                S.setdefault(t, "external")
        for a, (t, full) in img.code_relocs.items():
            if t == psp_prx.R_HI16 and full is not None and self.is_code(full) and full not in S \
                    and not full & 3 and full not in self.jt_entries and plausible(full):
                S.setdefault(full, "hilo")
        # stubs are handled separately (imports), never as functions
        return {a: k for a, k in S.items() if not (self.stub_lo <= a < self.stub_hi)}

    def find_code_islands(self):
        """Code linked into data sections (e.g. static constructors in .data): data
        pointers to a stack-frame prologue, plus the neighbouring entries of the same
        pointer table (the constructor list), traced to their ends."""
        img = self.img
        def prologue(a):
            w = img.u32(a)
            return (w >> 16) == 0x27BD and (w & 0x8000)
        def data_sec(a):
            for name, s, n, fl in img.section_list:
                if s <= a < s + n and not fl & 4 and fl & 2:
                    return s, s + n
            return None
        seeds = set()
        for p, t in img.ptr_relocs.items():
            sec = data_sec(t)
            if not sec or t & 3 or not prologue(t):
                continue
            seeds.add(t)
            for step in (4, -4):                  # the rest of the table
                q = p + step
                while q in img.ptr_relocs and data_sec(img.ptr_relocs[q]) == sec and \
                        not img.ptr_relocs[q] & 3 and abs(img.ptr_relocs[q] - t) < 0x10000:
                    seeds.add(img.ptr_relocs[q])
                    q += step
        if not seeds:
            return []
        self.code_ranges_base = list(self.code_ranges)
        islands = []
        for t in sorted(seeds):
            if islands and islands[-1][0] <= t < islands[-1][1]:
                continue
            lo, hi = data_sec(t)
            save = self.code_ranges
            self.code_ranges = [(lo, hi - lo)]
            end, _ = self.trace(t, hi)
            self.code_ranges = save
            if islands and t <= islands[-1][1] + 64:
                islands[-1] = (islands[-1][0], max(islands[-1][1], end))
            else:
                islands.append((t, end))
        self.island_seeds = seeds
        return [(s, e - s) for s, e in islands]

    def prescan_jumptables(self):
        """Targets of every `lui/addiu tab; addu; lw rX,0(..); jr rX` table in the code.
        Entries are taken while they point at code near the jr (switch cases)."""
        entries = set()
        for s_, n in self.code_ranges:
            for a in range(s_, s_ + n, 4):
                w = self.word(a)
                if w >> 26 or (w & 0x3F) != 8 or ((w >> 21) & 31) == 31:
                    continue
                jt = self.find_jumptable(a, max(s_, a - 0x100), a + 0x10000, near=0x10000)
                if jt:
                    entries.update(jt[1])
        return entries

    def looks_like_start(self, a):
        """A code address that begins a function: a stack-frame prologue, or the
        first non-padding word after a function's return / tail jump."""
        w = self.word(a)
        if (w >> 16) == 0x27BD and (w & 0x8000):          # addiu sp, sp, -N
            return True
        p = a - 4
        while p >= a - 64 and self.is_code(p) and self.word(p) == 0:
            p -= 4                                      # alignment padding
        if not self.is_code(p - 4):
            return True
        prev = self.word(p - 4)                          # p is the delay slot
        return prev == 0x03E00008 or (prev >> 26) == OP_J

    # ------------------------------------------------------------------
    def find_jumptable(self, jr_addr, fstart, fend, near=None):
        """Find the table feeding `jr rX` at jr_addr.  GCC emits
        lui rT,%hi(tab) ... lw rX,%lo(tab)(rT) ... jr rX; the HI16 reloc tells us `tab`."""
        reg = (self.word(jr_addr) >> 21) & 31
        lw_addr = None
        a = jr_addr - 4
        while a >= max(fstart, jr_addr - 64):
            w = self.word(a)
            if (w >> 26) == 0x23 and ((w >> 16) & 31) == reg:
                lw_addr = a
                break
            a -= 4
        if lw_addr is None:
            return None
        if near is None:
            ok = lambda t: fstart <= t < fend
        else:   # prescan: function bounds unknown yet
            ok = lambda t: abs(t - jr_addr) < near and self.is_code(t) and not t & 3

        def collect(tab):
            targets = []
            p = tab
            while p in self.img.ptr_relocs and ok(self.img.ptr_relocs[p]):
                targets.append(self.img.ptr_relocs[p])
                p += 4
            return (tab, targets) if targets else None

        # lui rB,%hi(tab); addu rB,rB,idx; lw rX,%lo(tab)(rB): the %lo is on the load itself
        lw = self.word(lw_addr)
        base = (lw >> 21) & 31
        a = lw_addr - 4
        while a >= max(fstart, lw_addr - 32):
            w = self.word(a)
            if (w >> 26) == 0x0F and ((w >> 16) & 31) == base:
                lo = lw & 0xFFFF
                tab = ((w & 0xFFFF) << 16) + (lo - 0x10000 if lo & 0x8000 else lo)
                if self.img.is_overlay or not self.is_code(tab):
                    found = collect(tab)
                    if found:
                        return found
                break
            a -= 4
        # lui rY,%hi(tab) (possibly in a delay slot far away); addiu rY,rY,%lo(tab);
        # addu rB,idx,rY; lw rX,0(rB)
        if (lw & 0xFFFF) == 0:
            a = lw_addr - 4
            while a >= max(fstart, lw_addr - 16):
                w = self.word(a)
                if (w >> 26) == 0x09 and ((w >> 21) & 31) == ((w >> 16) & 31):
                    y, lo = (w >> 16) & 31, w & 0xFFFF
                    lo = lo - 0x10000 if lo & 0x8000 else lo
                    b = fstart
                    while b < jr_addr:
                        u = self.word(b)
                        if (u >> 26) == 0x0F and ((u >> 16) & 31) == y:
                            tab = ((u & 0xFFFF) << 16) + lo
                            found = None if self.is_code(tab) and not self.img.is_overlay else collect(tab)
                            if found:
                                return found
                        b += 4
                    break
                a -= 4
        # nearest preceding HI16 whose full address is in rodata/data
        a = lw_addr - 4
        while a >= max(fstart, lw_addr - 64):
            r = self.img.code_relocs.get(a)
            if r and r[0] == psp_prx.R_HI16 and r[1] is not None and (self.img.is_overlay or not self.is_code(r[1])):
                return collect(r[1])
            a -= 4
        return None

    def trace(self, start, limit):
        """Trace control flow from start, never past limit. Returns (end, tailcalls)."""
        seen, todo = set(), [start]
        maxa = start
        tails = set()
        while todo:
            a = todo.pop()
            while start <= a < limit and a not in seen:
                seen.add(a)
                maxa = max(maxa, a)
                w = self.word(a)
                op = w >> 26
                bt = branch_target(w, a)
                if bt is not None:
                    maxa = max(maxa, a + 4)
                    if start <= bt < limit:
                        todo.append(bt)
                    else:
                        tails.add(bt)
                    if is_uncond_branch(w) and not (op == 1 and ((w >> 16) & 31) in (17,)):
                        break
                    a += 4  # likely branches may skip the delay slot; fallthrough after it
                    continue
                if op == OP_J:
                    tgt = ((a + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
                    seen.add(a + 4); maxa = max(maxa, a + 4)
                    if start <= tgt < limit:
                        todo.append(tgt)
                    else:
                        tails.add(tgt)
                    break
                if op == 0 and (w & 0x3F) == 8:          # jr
                    seen.add(a + 4); maxa = max(maxa, a + 4)
                    if ((w >> 21) & 31) != 31:
                        jt = self.find_jumptable(a, start, limit)
                        if jt:
                            self.jumptables[a] = jt
                            todo.extend(jt[1])
                        else:
                            self.notes.append(f"unresolved jr at {a:#x} in {start:#x}")
                    break
                if op == 0 and (w & 0x3F) == 0xD:        # break
                    break
                a += 4
        return maxa + 4, tails

    def valid_insn(self, a):
        import rabbitizer
        w = self.word(a)
        if (w >> 26) in (OP_J, OP_JAL) and not 0x08000000 <= ((w & 0x03FFFFFF) << 2) < 0x0A000000:
            return False   # a data pointer (0x08xxxxxx) decodes as j to nowhere
        return rabbitizer.Instruction(w, a, category=rabbitizer.InstrCategory.R4000ALLEGREX).isValid()

    def clean_function(self, a, limit):
        """Overlay gap code: a stack-frame prologue, or a body of valid instructions
        whose control flow ends in a return or jump within the gap."""
        w = self.word(a)
        if (w >> 16) == 0x27BD and w & 0x8000:
            return True
        notes, jts = self.notes, self.jumptables          # a probe: keep no side effects
        self.notes, self.jumptables = [], dict(jts)
        end, _ = self.trace(a, limit)
        self.notes, self.jumptables = notes, jts
        if end > limit or not all(self.valid_insn(p) for p in range(a, end, 4)):
            return False
        lo, hi = self.img.base, self.img.base + self.img.size
        for p in range(a, end, 4):
            w = self.word(p)
            bt = branch_target(w, p)
            if bt is not None and not a <= bt < end:
                return False                      # strings and tables branch into nowhere
            if (w >> 26) in (OP_J, OP_JAL):
                t = ((p + 4) & 0xF0000000) | ((w & 0x03FFFFFF) << 2)
                if not (lo <= t < hi or 0x08804000 <= t < 0x08B40000):
                    return False
            if (w >> 26) == 0 and (w & 0x3F) in (8, 9) and (w & 0x001FF7C0):
                return False                      # jr/jalr with junk in the unused fields
        last = self.word(end - 8) if end - a >= 8 else 0
        return last == 0x03E00008 or (last >> 26) == OP_J or \
            ((last & 0xFC1FFFFF) == 8 and last >> 21)

    # ------------------------------------------------------------------
    def run(self):
        kinds = dict(self.seeds())

        def region_end(a):
            for s, n in self.code_ranges:
                if s <= a < s + n:
                    return s + n
            return a

        # Fixpoint: trace every known function with the final bounds; tail-call
        # targets become new functions, untouched non-padding code becomes orphans.
        while True:
            self.jumptables, self.notes = {}, []
            starts = sorted(kinds)
            ends, new = {}, {}
            for i, s in enumerate(starts):
                limit = min(starts[i + 1] if i + 1 < len(starts) else 1 << 32, region_end(s))
                end, tails = self.trace(s, limit)
                ends[s] = (end, limit)
                for t in tails:
                    if self.is_code(t) and not (self.stub_lo <= t < self.stub_hi) and t not in kinds:
                        new[t] = "tailcall"
            for s in starts:
                a, limit = ends[s]
                while a < limit and self.word(a) == 0:
                    a += 4
                if a >= limit or a in kinds:
                    continue
                if not self.img.is_overlay:
                    new.setdefault(a, "orphan")
                    continue
                # overlays interleave data with code: look through the whole gap for code that
                # starts after padding or after a return, and traces like a function
                p = a
                while p < limit:
                    prev = self.word(p - 4)
                    starts_here = p == a or prev == 0 or self.word(p - 8) == 0x03E00008 or \
                        (self.word(p - 8) >> 26) == OP_J
                    if starts_here and self.word(p) != 0 and self.clean_function(p, limit):
                        new.setdefault(p, "orphan")
                        break
                    p += 4
            if not new:
                break
            # settle tail calls first; orphans only from a stable strong set
            tails_only = {a: k for a, k in new.items() if k == "tailcall"}
            kinds.update(tails_only or new)

        if self.img.is_overlay and not getattr(self, "_pruned", False):
            # data traced as code: drop weak seeds whose body holds an invalid instruction
            bad = set()
            for s in starts:
                if kinds[s] in ("entry", "jal", "external"):
                    continue
                end, _ = ends[s]
                for a in range(s, end, 4):
                    if not self.valid_insn(a):
                        bad.add(s)
                        break
            if bad:
                self._pruned = True
                self.pruned_seeds = bad
                self.seeds = lambda: {a: k for a, k in kinds.items() if a not in bad and k not in ("tailcall", "orphan")}
                return self.run()
        out = []
        for i, s in enumerate(starts):
            end, limit = ends[s]
            out.append({"start": s, "end": limit, "traced_end": end, "kind": kinds[s], "name": f"sub_{s:08X}"})
        return out


def analyze(an, img):
    funcs = an.run()
    from collections import Counter
    kinds = Counter(f["kind"] for f in funcs)
    covered = sum(f["end"] - f["start"] for f in funcs)
    total = sum(n for _, n in an.code_ranges)
    # rodata pointers into code that are neither jumptable targets nor function starts
    jt_targets = {t for _, ts in an.jumptables.values() for t in ts}
    fstarts = {f["start"] for f in funcs}
    stray = sorted({t for a, t in img.ptr_relocs.items() if an.is_code(t)} - jt_targets - fstarts)
    stats = {"functions": len(funcs), "kinds": kinds, "covered": covered, "code_bytes": total,
             "jumptables": len(an.jumptables), "jumptable_targets": len(jt_targets),
             "stray_code_pointers": len(stray), "notes": len(an.notes)}
    return {"functions": funcs,
            "jumptables": {f"{k:#x}": {"table": v[0], "targets": v[1]} for k, v in an.jumptables.items()},
            "stray_code_pointers": stray, "notes": an.notes, "stats": stats}


def load_overlays():
    """Every extracted overlay, keyed by its number; identical code shares one entry."""
    out = []
    for path in sorted((ROOT / "extracted/overlays").glob("*.elf")):
        out.append((int(path.name[:3]), path, psp_prx.load(path)))
    return out


def main():
    img = psp_prx.load(sys.argv[1] if len(sys.argv) > 1 else ROOT / "extracted/PSP_GAME/SYSDIR/BOOT.BIN",
                       ROOT / "data" / "nids.json")
    overlays = load_overlays()
    main_text = img.sections[".text"]
    stub_range = (min(i.stub for i in img.imports), max(i.stub for i in img.imports) + 8)

    # main <-> overlay references: code reached only from the other side is still a function
    into_main = set()
    for _, _, ov in overlays:
        crel, prel = ov.scan_refs(main_text[0], main_text[0] + main_text[1])
        into_main.update(t for _, t in crel.values())
        into_main.update(prel.values())
    slot_refs = {t for t in (v[1] for v in img.code_relocs.values()) if t is not None}

    an = Analyzer(img, extra_seeds=into_main)
    result = analyze(an, img)
    stats = result["stats"]

    ovl_out, seen = [], {}
    for num, path, ov in overlays:
        text = ov.sections[".text"]
        key = (ov.base, bytes(ov.mem[text[0] - ov.base:text[0] - ov.base + text[1]]))
        entry = {"id": num, "name": ov.overlay_name, "file": path.name, "base": ov.base,
                 "size": ov.size, "code": [text[0], text[0] + text[1]]}
        if key in seen:
            entry["same_code_as"] = seen[key]
        else:
            seen[key] = num
            hi = ov.base + ov.size
            oan = Analyzer(ov, extra_seeds={t for t in slot_refs if ov.base <= t < hi}, stub_range=stub_range)
            entry.update(analyze(oan, ov))
        ovl_out.append(entry)
    result["overlays"] = ovl_out
    json.dump(result, open(ROOT / "data" / "functions.json", "w"), indent=1)
    print(json.dumps(stats, indent=1, default=dict))
    for n in result["notes"][:20]:
        print(" ", n)
    print("stray samples:", [hex(x) for x in result["stray_code_pointers"][:20]])
    uniq = [o for o in ovl_out if "stats" in o]
    print(f"overlays: {len(ovl_out)} ({len(uniq)} with distinct code), "
          f"{sum(o['stats']['functions'] for o in uniq)} functions, "
          f"{sum(o['stats']['jumptables'] for o in uniq)} jump tables, "
          f"{sum(o['stats']['notes'] for o in uniq)} notes, "
          f"{sum(o['stats']['stray_code_pointers'] for o in uniq)} stray code pointers")
    for o in uniq:
        for n in o["notes"]:
            print(f"  [{o['id']:03d} {o['name']}] {n}")


if __name__ == "__main__":
    main()
