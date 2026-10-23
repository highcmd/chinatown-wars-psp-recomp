# GTA: Chinatown Wars: native PC port (static recompilation)

A static recompiler and runtime for the PSP game **Grand Theft Auto: Chinatown Wars** (USA, `ULUS-10490`,
v1.01). The game's MIPS code, including its 166 code overlays, is translated to C++ ahead of time and
runs natively on x86-64 Linux and Windows. The runtime provides a PSP kernel/HLE layer, an OpenGL 3.3
renderer for the GE, ATRAC3+ music and radio streaming, the SAS sound-effect mixer, and gamepad support.

This project shares its runtime with the
[SSX On Tour](https://github.com/highcmd/ssx-on-tour-psp-recomp) and
[Half-Minute Hero](https://github.com/highcmd/half-minute-hero-psp-recomp) recompilations.

**This repository contains no game data and no game code.** You need your own copy of the game,
dumped from a UMD you own. The setup decrypts and verifies that dump and generates everything
locally: the function analysis, the recompiled C++, and the executable. None of this output is
tracked by git (see `.gitignore`), so please don't commit it, upload it or share it.

## Quick start

You need **GTA: Chinatown Wars, USA release (`ULUS-10490`, v1.01)** dumped to an `.iso` from your own
UMD, using a PSP running custom firmware.

### Windows: the launcher

1. Download **`CTWLauncher.exe`** from the releases and start it. Nothing needs to be installed.
2. Click **Choose ISO…** and select your dump. The launcher checks it, downloads the compiler and
   libraries (about 300 MB, once), and builds the game in a few minutes.
3. Set the resolution and controls in the **Display** and **Controls** tabs, then press **PLAY**.

Without the launcher: install Python 3.10+, download this repository, run
`setup.bat D:\Games\chinatown-wars.iso` and start `dist\ctw-windows-x64\ctw.exe`.

### Linux

```sh
sudo apt install clang cmake ninja-build pkg-config python3-venv python3-tk \
    libsdl2-dev libavcodec-dev libavutil-dev libswscale-dev
./setup.sh /path/to/your/chinatown-wars.iso
./launcher.sh            # or: ./run.sh --res 1920x1080 --fullscreen
```

`./setup.sh <iso> --target windows` also builds the Windows version from Linux or WSL.

## Documentation

- [docs/BUILDING.md](docs/BUILDING.md): dependencies, dumping, the setup steps (EBOOT decryption,
  overlay extraction), the Windows build, troubleshooting
- [docs/OPTIONS.md](docs/OPTIONS.md): every setting (`ctw.ini` and flags), resolution, fullscreen
  and refresh rate, controls and remapping, saves, debugging variables
- [NOTES.md](NOTES.md): technical notes, above all how the code overlays are recompiled

## Status

Working (compared with the same ISO in PPSSPP):
- boot, the legal screen and the Rockstar Bink movie, the auto-save prompt, the intro comic cutscenes
- the first mission's opening: the airport, the ambush cutscene, the sinking-car minigame
- the HUD, the minimap and the minigames (each one is a code overlay loaded at run time)
- ATRAC3+ music and radio streaming, SAS sound effects
- the GPU renderer at up to 2880×1632 internal resolution, with the game's stencil shadows and bloom
- the keyboard and gamepads, including remapping
- the memory stick: the game finds it and turns auto-save on
- optional third-person camera: **F1** toggles it (`third_person_camera`, `camera_height` in ctw.ini);
  from Dark_Timur's ArtMoney cheat for PPSSPP, so like the original it also moves cutscene cameras

Not done yet, or not checked:
- full play-throughs: the game was tested through the opening of the first mission
- saves are written, but loading them back has not been tested
- ad hoc multiplayer and the online features are stubbed: no partner, no network
- the CPU (software) renderer draws the bloom pass wrongly (bright streaks); use the GPU renderer
- the game logic runs at its original 30 fps; `fps = 60` adds in-between frames (smooth motion,
  experimental; objects without a partner in the previous frame, such as some shadows, can lag)

## License

This project is licensed under the GNU General Public License v3.0 or later (`LICENSE`).
`runtime/vfpu/`, `runtime/sas/`, `runtime/assets/vfpu/`, `tools/prxdecrypt/Core/` and `data/nids.json` come
from [PPSSPP](https://github.com/hrydgard/ppsspp) (© PPSSPP Project, GPL-2.0-or-later), and
`tools/prxdecrypt/ext/libkirk/` from libkirk by Draan and contributors (GPL-3.0-or-later). The
Windows build ships SDL2 (zlib) and FFmpeg (GPL) DLLs; their licenses are copied into the build folder.

Grand Theft Auto: Chinatown Wars is © Rockstar Games / Take-Two Interactive. This project is not
affiliated with or endorsed by them or by Sony. "PSP" is a trademark of Sony Interactive Entertainment.
