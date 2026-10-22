#!/usr/bin/env python3
"""Build the PC port from your own copy of Grand Theft Auto: Chinatown Wars (USA, ULUS-10490, v1.01).

The repository holds no game data and no code derived from it. This script takes
the UMD image you dumped yourself (.iso, or a .zip holding one) and produces
everything locally:

  iso/<name>.iso         the image (unpacked from the zip, or a symlink to it)
  extracted/             EBOOT.BIN, decrypted to BOOT.BIN, the code overlays unpacked from
                         OVERLAYS.PAK, and a few headers (--extract-all: everything)
  data/functions.json    function analysis of BOOT.BIN
  build/gen/             recompiled C++ and the memory image
  build/tools/prxdecrypt the EBOOT decryptor (built from tools/prxdecrypt)
  build/cmake/ctw        the executable (Linux)
  dist/ctw-windows-x64/  ctw.exe with its DLLs and data (--target windows)

All of these are in .gitignore. Usage:

  tools/setup_from_iso.py <image.iso|image.zip> [--target linux|windows] [--no-build] [--force] [-j N]
"""
import argparse, glob, hashlib, os, pathlib, platform, shutil, struct, subprocess, sys, zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SECTOR = 2048

# Hashes identify the supported release; they are not game content.
GAME_ID = b"ULUS-10490"
EBOOT_SHA1 = "3891fcb776cf23e4cffd03bf3c0ff406dd9c22d0"   # PSP_GAME/SYSDIR/EBOOT.BIN (encrypted)
BOOT_SHA1 = "eba6b2b693cc3a0515d382b8f9d0ac807bdda889"    # the same, decrypted (BOOT.BIN on the disc is blank)


class SetupError(Exception):
    pass


def _print(msg):
    print(msg, flush=True)


# Where progress goes; the launcher replaces it with its log window.
log = _print


def die(msg):
    raise SetupError(msg)


def step(msg):
    log(f"==> {msg}")


# --- ISO 9660 ------------------------------------------------------------

class Iso:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        if os.path.getsize(path) < 17 * SECTOR:
            self.f.close()
            die(f"{path} is not a UMD/ISO image")
        pvd = self.read(16 * SECTOR, SECTOR)
        if pvd[0] != 1 or pvd[1:6] != b"CD001":
            self.f.close()
            die(f"{path} is not a UMD/ISO image")
        self.root = self._record(pvd, 156)

    def read(self, off, size):
        self.f.seek(off)
        data = self.f.read(size)
        if len(data) != size:
            die(f"{self.path} is truncated (read past the end at {off:#x})")
        return data

    @staticmethod
    def _record(buf, off):
        n = buf[off + 32]
        name = buf[off + 33:off + 33 + n]
        return {
            "lba": struct.unpack_from("<I", buf, off + 2)[0],
            "size": struct.unpack_from("<I", buf, off + 10)[0],
            "dir": bool(buf[off + 25] & 2),
            "name": name.decode("ascii", "replace").split(";")[0],
            "special": name in (b"\0", b"\1"),
        }

    def listdir(self, rec):
        data = self.read(rec["lba"] * SECTOR, rec["size"])
        off = 0
        while off < len(data):
            n = data[off]
            if n == 0:                        # records never cross a sector
                off = (off // SECTOR + 1) * SECTOR
                continue
            r = self._record(data, off)
            if not r["special"]:
                yield r
            off += n

    def walk(self, rec=None, prefix=""):
        for r in self.listdir(rec or self.root):
            path = prefix + r["name"]
            if r["dir"]:
                yield path, r
                yield from self.walk(r, path + "/")
            else:
                yield path, r

    def find(self, path):
        rec = self.root
        for part in path.split("/"):
            rec = next((r for r in self.listdir(rec) if r["name"].upper() == part.upper()), None)
            if rec is None:
                return None
        return rec

    def copy_to(self, rec, dst, h=None):
        self.f.seek(rec["lba"] * SECTOR)
        left = rec["size"]
        with open(dst, "wb") as out:
            while left:
                chunk = self.f.read(min(left, 1 << 20))
                if not chunk:
                    die(f"{self.path} is truncated")
                out.write(chunk)
                if h:
                    h.update(chunk)
                left -= len(chunk)

    def read_file(self, rec):
        return self.read(rec["lba"] * SECTOR, rec["size"])


# --- steps ---------------------------------------------------------------

def obtain_iso(src):
    """Return the path of a raw image, unpacking a zip into iso/ if needed."""
    src = src.resolve()
    if not src.exists():
        die(f"{src} does not exist")
    isodir = ROOT / "iso"
    isodir.mkdir(exist_ok=True)
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            members = [m for m in z.infolist() if m.filename.lower().endswith(".iso")]
            if len(members) != 1:
                die(f"{src} should contain exactly one .iso (found {len(members)})")
            m = members[0]
            dst = isodir / pathlib.Path(m.filename).name
            if dst.exists() and dst.stat().st_size == m.file_size:
                step(f"using already unpacked {dst.relative_to(ROOT)}")
                return dst
            step(f"unpacking {m.filename} ({m.file_size >> 20} MiB)")
            tmp = dst.with_suffix(".iso.part")
            with z.open(m) as i, open(tmp, "wb") as o:
                shutil.copyfileobj(i, o, 1 << 20)
            tmp.rename(dst)
            return dst
    if src.parent == isodir:
        return src
    probe = Iso(src)            # check it before linking it into iso/
    try:
        verify(probe)
    finally:
        probe.f.close()
    link = isodir / src.name
    if link.is_symlink() or link.exists():
        if link.resolve() != src:
            die(f"{link} already exists and points elsewhere; remove it first")
        return link
    try:
        link.symlink_to(src)
    except OSError:   # Windows without the symlink privilege: use the file where it is
        return src
    return link


_verified = set()


def verify(iso):
    if pathlib.Path(iso.path).resolve() in _verified:
        return
    step("checking the image")
    umd = iso.find("UMD_DATA.BIN")
    if umd is None or not iso.read_file(umd).startswith(GAME_ID):
        got = iso.read_file(umd)[:10].decode("ascii", "replace") if umd else "no UMD_DATA.BIN"
        die(f"this is not GTA: Chinatown Wars USA ({GAME_ID.decode()}); found: {got}")
    eboot = iso.find("PSP_GAME/SYSDIR/EBOOT.BIN")
    if eboot is None:
        die("PSP_GAME/SYSDIR/EBOOT.BIN is missing from the image")
    sha = hashlib.sha1(iso.read_file(eboot)).hexdigest()
    if sha != EBOOT_SHA1:
        die(f"EBOOT.BIN has SHA-1 {sha}, expected {EBOOT_SHA1}.\n"
            "       The image is a different revision or modified; only the retail "
            "ULUS-10490 v1.01 release is supported.")
    log(f"    {GAME_ID.decode()}, EBOOT.BIN {sha[:12]}… OK")
    _verified.add(pathlib.Path(iso.path).resolve())


# The runtime reads the game straight from the ISO; the recompiler only needs these.
OVERLAY_PAK = "PSP_GAME/USRDIR/WAD/OVERLAY/CTW_PSP_UMD_MASTER_SCEA/OVERLAYS.PAK"
NEEDED = ["UMD_DATA.BIN", "PSP_GAME/PARAM.SFO", "PSP_GAME/SYSDIR/EBOOT.BIN", OVERLAY_PAK]


def extract(iso, force, everything):
    out = ROOT / "extracted"
    stamp = out / (".complete" if everything else ".boot")
    if stamp.exists() and not force:
        step("extracted/ is up to date")
        return
    step("extracting " + ("the UMD file system" if everything else "EBOOT.BIN and OVERLAYS.PAK") + " to extracted/")
    if out.exists():
        shutil.rmtree(out)
    tmp = ROOT / "extracted.part"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    n = total = 0
    wanted = None if everything else {p.upper() for p in NEEDED}
    for path, rec in iso.walk():
        if wanted is not None and path.upper() not in wanted:
            continue
        dst = tmp / path
        if rec["dir"]:
            dst.mkdir(parents=True, exist_ok=True)
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        iso.copy_to(rec, dst)
        n += 1
        total += rec["size"]
    tmp.rename(out)
    log(f"    {n} files, {total >> 20} MiB")
    decrypt(out / "PSP_GAME/SYSDIR/EBOOT.BIN", out / "PSP_GAME/SYSDIR/BOOT.BIN")
    unpack_overlays(out / OVERLAY_PAK, out / "overlays")
    stamp.write_text(BOOT_SHA1 + "\n")


# --- EBOOT decryption -------------------------------------------------------

def host_compilers():
    """C and C++ compilers that build programs for the machine we run on."""
    if platform.system() == "Windows":
        import win_deps
        win_deps.log = log
        try:
            llvm = win_deps.ensure()["llvm"]
        except win_deps.DepsError as e:
            die(str(e))
        return (str(llvm / "bin/x86_64-w64-mingw32-clang.exe"), str(llvm / "bin/x86_64-w64-mingw32-clang++.exe"))
    for cc, cxx in (("clang", "clang++"), ("gcc", "g++"), ("cc", "c++")):
        if shutil.which(cc) and shutil.which(cxx):
            return cc, cxx
    die("no C/C++ compiler found (clang or gcc); see docs/BUILDING.md")


def build_prxdecrypt():
    """Compile tools/prxdecrypt (PPSSPP's PrxDecrypter + libkirk) for this machine."""
    src = ROOT / "tools/prxdecrypt"
    exe = ROOT / "build/tools" / ("prxdecrypt.exe" if platform.system() == "Windows" else "prxdecrypt")
    sources = sorted(src.rglob("*.c")) + sorted(src.rglob("*.cpp"))
    newest = max(p.stat().st_mtime for p in sorted(src.rglob("*")) if p.is_file())
    if exe.exists() and exe.stat().st_mtime >= newest:
        return exe
    step("building the EBOOT decryptor (tools/prxdecrypt)")
    cc, cxx = host_compilers()
    obj = ROOT / "build/tools/obj"
    obj.mkdir(parents=True, exist_ok=True)
    objs = []
    for c in (p for p in sources if p.suffix == ".c"):
        o = obj / (c.stem + ".o")
        run([cc, "-O2", "-I", src, "-c", c, "-o", o])
        objs.append(o)
    cpp = [p for p in sources if p.suffix == ".cpp"]
    extra = ["-static"] if platform.system() == "Windows" else []
    run([cxx, "-O2", "-std=c++17", "-I", src, *cpp, *objs, "-o", exe, *extra])
    return exe


def decrypt(eboot, boot):
    """EBOOT.BIN (~PSP, encrypted) -> BOOT.BIN (the plain executable the recompiler reads)."""
    tool_exe = build_prxdecrypt()
    step("decrypting EBOOT.BIN")
    run([tool_exe, eboot, boot])
    data = boot.read_bytes()
    if data[:2] == b"\x1f\x8b":   # gzip-compressed module
        import gzip
        data = gzip.decompress(data)
        boot.write_bytes(data)
    sha = hashlib.sha1(data).hexdigest()
    if sha != BOOT_SHA1:
        die(f"the decrypted executable has SHA-1 {sha}, expected {BOOT_SHA1}")
    log(f"    BOOT.BIN {sha[:12]}… OK")


def unpack_overlays(pak, dst):
    """OVERLAYS.PAK -> one ELF per overlay (NNN_name.elf).

    Layout: "20KP", u32 count at 0x24, u32 sector size at 0x28, u16 start sectors (relative to
    0x800) from 0x2c. Entry 0 is a table of name hashes; every other entry is "10SA", u32 packed
    size, u32 size, zlib data: a small ELF that loads at a fixed address in one of two slots.
    """
    import zlib
    step("unpacking the code overlays")
    data = pak.read_bytes()
    if data[:4] != b"20KP":
        die(f"{pak.name}: unexpected header {data[:4]!r}")
    count, sec = struct.unpack_from("<II", data, 0x24)
    starts = struct.unpack_from(f"<{count}H", data, 0x2c)
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    for i in range(1, count):
        off = 0x800 + starts[i] * sec
        if data[off:off + 4] != b"10SA":
            die(f"{pak.name}: overlay {i} has no 10SA header")
        packed, size = struct.unpack_from("<II", data, off + 4)
        elf = zlib.decompress(data[off + 12:off + 12 + packed])
        if len(elf) != size or elf[:4] != b"\x7fELF":
            die(f"{pak.name}: overlay {i} did not unpack")
        shoff, = struct.unpack_from("<I", elf, 32)
        shstr, = struct.unpack_from("<H", elf, 50)
        name_off, = struct.unpack_from("<I", elf, shoff + 40)          # section 1's name
        tab, = struct.unpack_from("<I", elf, shoff + 40 * shstr + 16)
        name = elf[tab + name_off:elf.index(b"\0", tab + name_off)].decode().removeprefix(".overlay_")
        (dst / f"{i:03d}_{name}.elf").write_bytes(elf)
        n += 1
    log(f"    {n} overlays")


FROZEN = getattr(sys, "frozen", False)   # inside the packaged launcher


def run(cmd):
    """Run a command, passing its output to log() line by line."""
    log("    $ " + " ".join(str(c) for c in cmd))
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW: no console flashing up
    p = subprocess.Popen([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, creationflags=flags)
    for line in iter(p.stdout.readline, b""):
        log("    " + line.decode("utf-8", "replace").rstrip())
    if p.wait():
        die(f"command failed with exit code {p.returncode}")


class _LogWriter:
    def __init__(self):
        self.buf = ""

    def write(self, s):
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            log("    " + line)
        return len(s)

    def flush(self):
        pass


def run_tool(script):
    """Run one of tools/*.py: a child Python normally, in-process in the launcher."""
    if not FROZEN:
        run([sys.executable, script])
        return
    import contextlib, runpy
    log(f"    $ {script.name}")
    old_argv, old_path = sys.argv, list(sys.path)
    sys.argv = [str(script)]
    sys.path.insert(0, str(script.parent))
    try:
        with contextlib.redirect_stdout(_LogWriter()):
            runpy.run_path(str(script), run_name="__main__")
    except SystemExit as e:
        if e.code not in (None, 0):
            die(f"{script.name} failed: {e.code}")
    finally:
        sys.argv, sys.path[:] = old_argv, old_path


def recompile(force):
    try:
        import rabbitizer  # noqa: F401
    except ImportError:
        die("the Python package 'rabbitizer' is missing; run ./setup.sh, "
            "or: pip install -r requirements.txt")
    funcs = ROOT / "data/functions.json"
    if force or not funcs.exists():
        step("analysing BOOT.BIN (function discovery)")
        run_tool(ROOT / "tools/analyze.py")
    else:
        step("data/functions.json is up to date")
    step("recompiling MIPS to C++ (build/gen)")
    run_tool(ROOT / "tools/recomp.py")


_tools = {}


def tool(name):
    """Find a build tool: downloaded (Windows), on PATH, or next to this Python (pip cmake/ninja)."""
    if name in _tools:
        return _tools[name]
    here = pathlib.Path(sys.executable).parent
    found = shutil.which(name) or shutil.which(name, path=str(here))
    if not found:
        die(f"'{name}' not found; see docs/BUILDING.md for the build dependencies")
    return found


def build(iso_path, jobs):
    if not shutil.which("clang++"):
        die("'clang++' not found; see docs/BUILDING.md for the build dependencies")
    step("configuring and building")
    bdir = ROOT / "build/cmake"
    run([tool("cmake"), "-S", ROOT, "-B", bdir, "-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={tool('ninja')}",
         "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_CXX_COMPILER=clang++",
         f"-DCTW_ISO={iso_path.resolve()}"])
    run([tool("ninja"), "-C", bdir, "ctw"] + (["-j", str(jobs)] if jobs else []))
    step("done. Start the game with ./run.sh (options: ./run.sh --help)")
    return {"exe": bdir / "ctw", "cwd": ROOT / "run"}


WINDOWS_README = """GTA: Chinatown Wars - native Windows build (static recompilation)
=================================================================

1. Put your GTA: Chinatown Wars (USA, ULUS-10490) .iso in this folder, next to ctw.exe,
   or write its location into ctw.ini:   iso = D:\\Games\\Chinatown Wars.iso
2. Start ctw.exe.

Settings: copy ctw.ini.example to ctw.ini and edit it (resolution, fullscreen,
controls, ...). The full list is in docs/OPTIONS.md of the source repository.
Saves are written to ms0\\PSP\\SAVEDATA\\ here; the log goes to ctw.log.

This folder was generated from your own copy of the game (image.bin is derived
from it). Do not share it. ctw.exe is GPL-3.0-or-later (LICENSE.txt); SDL2 is
zlib-licensed and FFmpeg is GPL (see licenses\\).
"""


def cm(path):
    """A path for a CMake -D argument: forward slashes (backslashes are escapes in CMake)."""
    return pathlib.Path(path).as_posix()


def build_windows(iso_path, jobs):
    import win_deps
    win_deps.log = log
    try:
        deps = win_deps.ensure()
    except win_deps.DepsError as e:
        die(str(e))
    _tools.update(deps.get("tools", {}))
    step("configuring and building for Windows x64")
    bdir = ROOT / "build/win64"
    run([tool("cmake"), "-S", ROOT, "-B", bdir, "-G", "Ninja", f"-DCMAKE_MAKE_PROGRAM={cm(tool('ninja'))}",
         "-DCMAKE_BUILD_TYPE=Release",
         f"-DCMAKE_TOOLCHAIN_FILE={cm(ROOT / 'cmake/llvm-mingw.cmake')}",
         f"-DLLVM_MINGW={cm(deps['llvm'])}",
         f"-DCMAKE_PREFIX_PATH={cm(deps['sdl2'])}",
         f"-DCTW_FFMPEG_ROOT={cm(deps['ffmpeg'])}",
         "-DCTW_NATIVE_ARCH=OFF"])
    run([tool("ninja"), "-C", bdir, "ctw"] + (["-j", str(jobs)] if jobs else []))

    step("assembling dist/ctw-windows-x64")
    dist = ROOT / "dist/ctw-windows-x64"
    dist.mkdir(parents=True, exist_ok=True)
    shutil.copy2(bdir / "ctw.exe", dist)
    shutil.copy2(deps["sdl2"] / "bin/SDL2.dll", dist)
    for prefix in ("avcodec-", "avutil-", "swscale-", "swresample-"):
        for dll in glob.glob(str(deps["ffmpeg"] / "bin" / f"{prefix}*.dll")):
            shutil.copy2(dll, dist)
    shutil.copy2(ROOT / "build/gen/image.bin", dist)
    shutil.copytree(ROOT / "runtime/assets", dist / "assets", dirs_exist_ok=True)
    shutil.copy2(ROOT / "ctw.ini.example", dist)
    shutil.copy2(ROOT / "LICENSE", dist / "LICENSE.txt")
    lic = dist / "licenses"
    lic.mkdir(exist_ok=True)
    shutil.copy2(deps["ffmpeg"] / "LICENSE.txt", lic / "FFmpeg-LICENSE.txt")
    sdl_lic = deps["sdl2"].parent / "LICENSE.txt"
    if sdl_lic.exists():
        shutil.copy2(sdl_lic, lic / "SDL2-LICENSE.txt")
    (dist / "README.txt").write_bytes(WINDOWS_README.replace("\n", "\r\n").encode())
    ini = dist / "ctw.ini"
    text = ini.read_text(encoding="utf-8") if ini.exists() else ""
    has_iso = any(l.split("#")[0].split("=")[0].strip() == "iso" for l in text.splitlines())
    if platform.system() == "Windows" and not has_iso:
        ini.write_text(text + ("" if text.endswith("\n") or not text else "\n") + f"iso = {iso_path.resolve()}\n",
                       encoding="utf-8")
        has_iso = True
    if has_iso or any(dist.glob("*.iso")):
        where = "ctw.ini points at your ISO"
    else:
        where = f"copy your ISO ({iso_path.name}) into that folder, or set 'iso = <path>' in ctw.ini there"
    step(f"done: {dist}\n    {where}, then start ctw.exe")
    return {"exe": dist / "ctw.exe", "cwd": dist}


def default_target():
    return "windows" if platform.system() == "Windows" else "linux"


def setup(image, target=None, build_it=True, force=False, extract_all=False, jobs=0):
    """The whole pipeline. Returns {"exe", "cwd"} of the built game (None with build_it=False)."""
    iso_path = obtain_iso(pathlib.Path(image))
    iso = Iso(iso_path)
    try:
        verify(iso)
        extract(iso, force, extract_all)
    finally:
        iso.f.close()
    recompile(force)
    if not build_it:
        return None
    if (target or default_target()) == "windows":
        return build_windows(iso_path, jobs)
    return build(iso_path, jobs)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("image", type=pathlib.Path, help="your GTA: Chinatown Wars USA dump (.iso or .zip)")
    ap.add_argument("--target", choices=["linux", "windows"], default=default_target(),
                    help="what to build (default: this system); windows works from Linux/WSL too")
    ap.add_argument("--no-build", action="store_true", help="stop after generating build/gen")
    ap.add_argument("--force", action="store_true", help="redo extraction and analysis")
    ap.add_argument("--extract-all", action="store_true",
                    help="extract the whole UMD (only needed to run with --umd <dir> instead of the ISO)")
    ap.add_argument("-j", "--jobs", type=int, default=0, help="parallel compile jobs")
    a = ap.parse_args()
    try:
        setup(a.image, a.target, not a.no_build, a.force, a.extract_all, a.jobs)
    except SetupError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
