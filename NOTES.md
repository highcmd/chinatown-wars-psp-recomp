# GTA: Chinatown Wars (PSP, USA v1.01): static recompilation to PC

Built from the Half-Minute Hero recompiler, which was built from SSX On Tour (same runtime, tools and
launcher). These notes cover what this game needed on top of those.

## Input
- `UMD_DATA.BIN` = `ULUS-10490`, PARAM.SFO DISC_VERSION 1.01, PSP_SYSTEM_VER 6.00.
- `PSP_GAME/SYSDIR/BOOT.BIN` is all zeros; the code is the encrypted `EBOOT.BIN` (SHA-1 3891fcb776cf…),
  decrypted by `tools/prxdecrypt` (PPSSPP PrxDecrypter + libkirk) to an ET_EXEC at 0x08804000
  (SHA-1 eba6b2b693cc…). 3.3 MB of `.text`, 256 imports.
- `USRDIR/WAD/OVERLAY/CTW_PSP_UMD_MASTER_SCEA/OVERLAYS.PAK` holds the **code overlays**:
  "20KP", u32 count (167) at 0x24, u32 sector size at 0x28, u16 start sectors (relative to 0x800)
  from 0x2c. Entry 0 is a table of name hashes. Every other entry is "10SA", u32 packed size, u32 size,
  zlib data: a small ELF (type 0xFFA8) with one WAX section `.overlay_<name>` at a fixed address.
  `setup_from_iso.py` unpacks them to `extracted/overlays/NNN_name.elf`.
- Two slots, disjoint: 114 mission/mode overlays at 0x08b87460 (up to 172 KB) and 52 "apps"
  (HUD, map, pause, minigames) at 0x08bb2480 (up to 87 KB). The main ELF's `.overlays` section marks
  the area (0x08b8744c..0x08bc7fa0).
- Overlay header (16 bytes at the slot base): [id, init function, ?, ?]. The game's loader
  (thread "overlayloader", OverlayLoadWake/OverlayLoadLock semas) inflates an overlay into its slot,
  calls IcacheInvalidateAll, then calls the init function.

## Recompiling the overlays
- `psp_prx.py` loads an overlay ELF like an ET_EXEC. Code, rodata and data of its object files are
  interleaved in the one section, so everything after the header is called `.text` and the pointer
  scan reads every word.
- `analyze.py` analyses the executable and every overlay:
  - Cross references become seeds on both sides: overlay `jal`s/pointers into the executable (780
    functions are reached only from overlays) and the executable's `jal`s into the slots (92 calls).
  - Overlay seeds must look like code: no zero word (zero-filled data next to code), header pointers
    are strong seeds, weak seeds whose trace hits an invalid Allegrex instruction or a `j` to nowhere
    (a data pointer 0x08xxxxxx decodes as `j`) are dropped.
  - Gaps between functions are searched for leaf functions without a prologue (`jr ra` stubs in
    vtables): code after padding or a return that traces cleanly (valid instructions, branches stay
    inside, `jr` encodings valid). Probe traces have no side effects.
  - Jump tables: this compiler also emits `lui at,%hi; addu at,at,idx; lw at,%lo(at); jr at` and
    `lui` in a far branch's delay slot with `addiu rY,%lo; addu; lw 0(..)`. Both are recognised
    (203 tables in the executable, 137 in overlays).
  - Result: 12222 functions in the executable, 22579 in the overlays.
- `recomp.py` writes one `recomp_ovl_NNN.cpp` per overlay with functions `O<id>_<addr>`; an overlay
  function ends where its trace ends (data follows). Calls go directly to the same overlay, to the
  executable (`F_…`) and to import stubs; anything else is `rt_call`.
- Each overlay gets a **signature**: (address, word) pairs of its traced code, chosen so it differs
  from every other overlay of its slot within their common range (memory past a shorter overlay still
  holds the previous one). `rt_call` into a slot checks the current overlay's signature (a few word
  compares) and otherwise finds the overlay that matches. No hook into the game's loader is needed.

## Runtime fixes and additions (generic PSP behaviour)
- **Stencil in GL**: once a shader writes `gl_FragStencilRefARB`, that value replaces glStencilFunc's
  reference in every invocation and is undefined where it isn't written. The shader now always
  writes it (the export value, or the test reference). Before, every "stencil != 0x80" shadow pass
  covered the whole screen: the game looked far too dark. Affects SSX and HMH too.
- **Alpha is the stencil**: without the stencil test, drawing leaves the framebuffer alpha alone
  (PPSSPP DrawPixel and GPUStateUtils); only clears and stencil ops change it. GL and CPU renderers.
- Lighting: the material-update bits take the vertex colour only when the vertex has one.
- Timeouts: a timeout variable holding 0 times out at once. The PSP writes 0 there after a timeout
  and games reuse it; it used to wait forever (WaitThreadEnd loop after the Bink movie).
- `sceKernelExitDeleteThread` and module_start's return delete the thread and free its stack. The
  game sizes its heap from MaxFreeMemSize; the leaked 256 KB made overlay loads fail (NULL buffer).
- VBlank sub-interrupt handlers (InterruptManager) run as guest interrupts every vblank.
- ATRAC streaming rewritten as a ring with an `avail` count: SetHalfwayBufferAndGetID,
  GetBufferInfoForResetting/ResetPlayPosition (the radio starts each station mid-song),
  GetNextDecodePosition, GetSoundSample, GetBitrate, looping streams.
- sceAudioOutput2* (one more stereo channel), sceCtrlPeekBufferPositive, SleepThreadCB,
  sysclock conversions, RTC clock/tick functions, sceIoCloseAsync, VolatileMemTryLock,
  CpuResumeIntrWithSync, `ms0:/PSP/SAVEDATA` created at start (the game probes ms0: before saving).
- `vsync2` (VFPU) is a no-op like `vsync`.

## Cheats: third-person camera (F1)
`data/cheats.json` lists instructions of BOOT.BIN that the recompiler wraps in a test of a `g_cheats`
bit (`"nop"`: skipped while the cheat is on) or replaces by a call into `game_hooks.cpp` (`"call:fn"`).
The third-person camera follows Dark_Timur's ArtMoney table for PPSSPP (2015, "GTA San Andreas-like
camera"); its addresses match this v1.01 executable word for word:
- 46 stores of the camera height (+0x108 of the camera object) are skipped;
- `lh a0, 0x12C(s0)` in the view-matrix builder F_088559AC (the pitch) gives 0, and the same hook
  holds the height at `camera_height` (15000; the game uses ~111700) and puts 111700 back when F1
  turns it off.
Cutscene cameras are affected too while it is on, as in the original cheat.

## Savestates (F5 / F9)
`runtime/src/savestate.cpp`. Every call in generated code pushes (address of the call
instruction, target) on the running thread's shadow call stack (`g_ssp`, one per thread). A
state is taken from the scheduler while every thread waits inside exactly one system call and
the GE is idle: guest RAM/VRAM/scratchpad, threads (registers + shadow stack), kernel objects,
open files (path + position), audio channels, ATRAC streams, GE registers, dialogs. Host
stacks are not saved, so states survive rebuilds. Loading gives each waiting thread a new fiber
that re-enters its calls: a generated function entered while `g_resuming` switches on the next
recorded call site, makes that call and continues after it; the innermost call is the system
call, made again (its wait starts afresh). The guest clock continues from the saved time.
Not possible while a video plays. Timers are rebuilt (vblank, alarms).

## 60 fps: why the game stays at 30
F_0890D53C ends each frame with `while (vblanks since the last flip < 2) sceDisplayWaitVblankStart()`
(`sltiu a0,a0,2` at 0x0890D680). Comparing with 1 does give 60 fps, but the whole game then runs twice
as fast (cutscenes, scripts, movement): the logic advances one fixed step per frame. Memory dumps of
30 and 60 fps runs (`CTW_DUMP_MEM`) show no time-step variable (no float or integer that halves at
60 fps), only frame counters that double, and the code holds no 1/30 s, 33 ms or 16.7 ms constant; the only
millisecond clock (0x08BF1DD0) follows real time. The engine is the DS game's fixed-point, frame-locked
design, so 60 fps comes from in-between frames instead (`fps = 60`, ge_gl.cpp):
- With interpolation on, `gl_ge_draw` records each draw (state, its texture resolved to a GL texture,
  clip-space vertices) instead of executing it. A texture whose pixels change after a recorded draw used
  it gets a new GL texture, so every recorded draw keeps its picture.
- At FINISH the frame runs twice. First every draw that has a partner in the previous frame (same
  texture, vertex count and target stride, n-th occurrence of that key) gets its vertices halfway
  between the two frames; partners whose screen positions moved more than half the screen are refused
  (camera cuts, a different object). Every target drawn is then copied to its `midTex`. Then the frame
  runs as recorded, so all targets end in their real state.
- The present thread shows a target's `midTex` at the first vblank after the game flips to it and the
  real picture at the next one: 60 pictures per second, one 60 Hz frame of extra latency.
- The target address is not part of the key: the game alternates two display buffers. 86-95 % of the
  draws find a partner in the first mission; the others (new objects, some shadow volumes) are drawn at
  their new position.

## Window and hotkeys
- The hidden window that holds the GE's GL context keeps SDL from sending SDL_QUIT when the game window
  closes, so SDL_WINDOWEVENT_CLOSE quits as well (X button, Alt+F4).
- `osd.cpp`: a 5x7 bitmap font box in the top-left corner, drawn by both presenters: the FPS meter (F2,
  `show_fps`) and a 2 s message after a hotkey.

## Known issues
- The CPU renderer draws the bloom wrong (bright horizontal streaks): its render-to-texture of the
  0x04110000/0x04132000 buffers with changing strides doesn't match. The GPU renderer is right.
- Saves load untested; ad hoc / online stubbed.

## Comparing with PPSSPP
`tools/ppsspp-headless-compare.patch` (for PPSSPP 1.20.4, `patch -p1` in its source tree) adds
`PPSSPP_INPUT` (same syntax as `CTW_INPUT`, in emulated seconds) and `PPSSPP_SHOT_EVERY` (displayed
framebuffer to `pshot_NNN.ppm`) to `PPSSPPHeadless`. Run the ISO with `--graphics=software` to get
reference frames of the same scene:

    PPSSPP_SHOT_EVERY=10 PPSSPP_INPUT="22=cross:0.5,27=cross:0.5,40=cross" \
        PPSSPPHeadless chinatown-wars.iso --graphics=software --timeout=600

## Build & run
    ./setup.sh <your ULUS-10490 dump>      # decrypt, unpack overlays, analyse, recompile, build
    ./launcher.sh  |  ./run.sh [--res WxH] [--fullscreen] ...
Debug env vars: CTW_LOG, CTW_INPUT, CTW_SHOT_EVERY, CTW_FPS, CTW_GETRACE_AT (now with lighting, fog
and clear state), CTW_DUMP_RT (render targets and stencil next to each screenshot), CTW_RTTDBG,
CTW_CALLERS_AT, CTW_HLESTATS. A read into NULL logs a guest backtrace.
