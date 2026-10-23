# Options and configuration

The easiest way to change settings is the **launcher** (`CTWLauncher.exe` on Windows, `./launcher.sh`
on Linux): its Display and Controls tabs write `ctw.ini` for you. This page describes the file
and the command-line flags behind it.

You can set options in two places:

1. **`ctw.ini`**: the configuration file. On Linux it is read from the directory the game starts
   in; `run.sh` always starts it in `run/`, so the file is `run/ctw.ini`. On Windows it is read
   from the folder of `ctw.exe`. Copy [`ctw.ini.example`](../ctw.ini.example) to begin.
2. **Command-line flags**: `./run.sh --res 1920x1080 --fullscreen`. A flag overrides the same key in the file.

In `ctw.ini`, write `key = value`, one per line; `#` starts a comment. On the command line, use
`--key value`; dashes and underscores are interchangeable (`--render-scale` = `--render_scale`).
`./run.sh --help` prints a short summary.

## Settings

| `ctw.ini` key | Flag | Values | Default | What it does |
|---|---|---|---|---|
| `resolution` (or `res`) | `--res WxH` | e.g. `1920x1080` | `960x544` | window size |
| `scale` | `--scale N` | `1`, `2`, … | none | shorthand for a window of 480·N × 272·N |
| `fullscreen` | `--fullscreen` / `--windowed` | `true`/`false` | `false` | fullscreen; F11 toggles it while playing |
| `refresh` | `--refresh HZ` | `0` or Hz | `0` | with `fullscreen`: `0` = borderless at the desktop mode; a rate switches the monitor to `resolution` at that rate, see [Fullscreen](#fullscreen-and-refresh-rate) |
| `renderer` | `--renderer R` | `gl`, `software` | `gl` | `gl` = GPU (OpenGL 3.3); `software` = CPU reference renderer |
| `render_scale` | `--render-scale N` | `0`–`6` | `0` (auto) | internal resolution, see [Resolution](#resolution) |
| `filter` | `--filter F` | `linear`, `nearest` | `linear` | filter used to fit the picture into the window |
| `vsync` | `--vsync` | `true`/`false` | `false` | sync presentation to the monitor refresh rate |
| `deadzone` | `--deadzone N` | `0`–`32767` | `8000` | left-stick deadzone; raise it if the rider drifts |
| `right_stick_dpad` | `--right-stick-dpad` | `true`/`false` | `false` | the right stick also works as the D-pad (menus) |
| `show_fps` | `--show-fps` | `true`/`false` | `false` | FPS meter in the top-left corner; F2 toggles it while playing |
| `third_person_camera` | `--third-person-camera` | `true`/`false` | `false` | start with the third-person camera; F1 toggles it while playing |
| `camera_height` | `--camera-height N` | 1000..200000 | `15000` | height of the third-person camera (the game's own top-down camera is ~111700) |
| `hud_scale` | `--hud-scale N` | `100`, `75`, `50` | `100` | HUD size in percent: each element shrinks towards its corner or edge of the screen; F3 cycles it while playing (and saves it here). Full-screen menus (PDA, pause, map) keep their size |
| `pad_mapping` | `--pad-mapping STR` | SDL mapping line | none | adds a mapping for a pad SDL doesn't know, see [Gamepads](#gamepads) |
| `iso` | `--iso FILE` | path | see [Paths](#paths) | your UMD image |
| `key_<button>` | none | key names | see [Remapping](#remapping) | keyboard keys for a PSP button |
| `pad_<button>` | none | button names | see [Remapping](#remapping) | gamepad buttons for a PSP button |

In `ctw.ini`, booleans accept `true`/`1`/`on`/`yes`; anything else counts as false.

Example `run/ctw.ini` for a 1080p monitor:

```ini
resolution = 1920x1080
fullscreen = true
render_scale = 0      # auto -> 4 (1088 px of internal height)
filter = linear
vsync = true
```

### Resolution

The PSP renders at 480×272. The game is drawn at **480·N × 272·N** on the GPU (`render_scale = N`).
This is real rendering at the higher resolution, with sharp edges and detailed distant geometry, not a
stretched 480×272 image. The finished frame is then fitted into the window with its 480:272 aspect
ratio kept (letterboxed when needed) and filtered with `filter`.

| `render_scale` | Internal resolution | Good for |
|---|---|---|
| 1 | 480×272 | original look |
| 2 | 960×544 | |
| 3 | 1440×816 | 900p and smaller screens |
| 4 | 1920×1088 | 1080p |
| 5 | 2400×1360 | 1440p |
| 6 | 2880×1632 | 1440p+ with supersampling, 4K |

`0` (auto) picks the multiple of 272 nearest to the window height: the desktop height in
fullscreen, otherwise the height from `resolution`. For the sharpest picture, use a window height that
is a multiple of 272 (544, 816, 1088, …) or let auto pick, and keep `filter = linear`.

The GPU cost grows with N². The game holds its 30 fps in the city at the default scale on an
integrated GPU (a Radeon "Phoenix" APU). The `software` renderer is much slower, draws the bloom pass
wrongly, and is there only as a reference.

### Fullscreen and refresh rate

Fullscreen comes in two kinds:

- **Borderless** (`refresh = 0`, the default): the window covers the screen and the monitor stays at
  the desktop's resolution and refresh rate. Switching in and out (F11) is instant.
- **Exclusive** (`refresh = 144`, for example): the monitor switches to `resolution` at that refresh
  rate, or the closest mode it supports. `ctw.log` shows the mode it got
  (`fullscreen mode 2560x1440 @ 144 Hz`). Use it to run the game at a refresh rate other than the
  desktop's, for example 60 Hz on a 144 Hz monitor so that `vsync = true` paces the game evenly.

```ini
fullscreen = true
resolution = 2560x1440
refresh = 60
vsync = true
```

The launcher lists the refresh rates your monitor offers for the chosen size. On Linux under
Wayland, compositors don't let programs change the mode, so exclusive fullscreen behaves like
borderless there.

### Frame rate

The game logic runs at 30 fps, like on the PSP (one fixed step per frame; it renders every second
vblank). `fps = 60` (`--fps 60`, launcher: Frame rate 60) shows an in-between picture after every game
frame: the frame is drawn a second time with every vertex halfway between its position in the previous
frame and in this one. Motion and camera pans look like 60 fps, the game itself still runs at 30, and
the picture is one 60 Hz frame later. Objects that can't be paired with the previous frame (new ones,
some effects and shadows) keep their new position in the in-between picture. GPU renderer only; F2
shows e.g. "60 FPS (GAME 30)".

Use `vsync = true` with a 60 Hz mode (or `refresh = 60` in fullscreen) for the smoothest motion.

### Gamepads

Any pad that SDL2 recognises as a game controller should work (Xbox, PlayStation, Switch Pro and most
clones). It can be plugged in before or after the game starts, and several pads at once are fine.
Tested with a wired Xbox 360 pad (in SSX On Tour, which shares this runtime).

| PSP | Xbox-style pad | Keyboard |
|---|---|---|
| D-pad | D-pad (and the right stick with `right_stick_dpad`) | arrow keys |
| Analog nub | left stick | I / J / K / L |
| ✕ Cross | A | Z |
| ○ Circle | B | X |
| □ Square | X | A |
| △ Triangle | Y | S |
| L | LB or LT | Q |
| R | RB or RT | E |
| Start | Start | Enter |
| Select | Back | Backspace or right Shift |
| none | none | F11 = toggle fullscreen |
| none | none | F1 = toggle the third-person camera |
| none | none | F2 = show/hide the FPS meter |
| none | none | F3 = HUD size 100 % → 75 % → 50 % (kept in `ctw.ini` as `hud_scale`) |
| none | none | F5 = quick save (a savestate in `savestates/quick1.ctwstate`) |
| none | none | F9 = quick load |
| none | none | window close button / Alt+F4 = quit |

Keyboard and pads can be used at the same time.

### Remapping

Every PSP button can be bound to other keys and pad buttons in `ctw.ini`, or in the launcher's
Controls tab. Separate several bindings with commas; `none` removes all of them.

```ini
key_cross = Space, Z
key_select = none
pad_l = leftshoulder
pad_r = rightshoulder, righttrigger
```

| PSP button | `ctw.ini` names |
|---|---|
| D-pad | `up`, `down`, `left`, `right` |
| ✕ ○ □ △ | `cross`, `circle`, `square`, `triangle` |
| shoulders, Start, Select | `l`, `r`, `start`, `select` |
| analog nub, keyboard only | `analog_up`, `analog_down`, `analog_left`, `analog_right` |

- **Keys** use SDL's key names: `A`–`Z`, `0`–`9`, `Return`, `Space`, `Backspace`, `Tab`,
  `Left Shift`, `Right Shift`, `Left Ctrl`, `Right Ctrl`, `Left Alt`, `Right Alt`, `Up`, `Down`, `Left`,
  `Right`, `Keypad 0`–`Keypad 9`, `Keypad Enter`, `F1`–`F12`, and so on. Letters refer to the key's
  position on a US layout.
- **Pad buttons** use SDL's game controller names: `a`, `b`, `x`, `y`, `leftshoulder`, `rightshoulder`,
  `lefttrigger`, `righttrigger`, `back`, `start`, `guide`, `leftstick`, `rightstick`, `dpup`, `dpdown`,
  `dpleft`, `dpright`.
- The left stick is always the analog nub. Unknown names are reported in `ctw.log`.

If your pad isn't recognised (nothing happens, or the buttons are mixed up), create a mapping line
with a tool such as the SDL2 Gamepad Tool or
[SDL_GameControllerDB](https://github.com/mdqinc/SDL_GameControllerDB) and put it in `ctw.ini`:

```ini
pad_mapping = 03000000xxxxxxxxxxxxxxxxxxxxxxxx,My Pad,a:b0,b:b1,x:b2,y:b3,back:b6,start:b7,leftshoulder:b4,rightshoulder:b5,dpup:h0.1,dpdown:h0.4,dpleft:h0.8,dpright:h0.2,leftx:a0,lefty:a1,lefttrigger:a2,righttrigger:a5,platform:Linux,
```

SDL also reads the `SDL_GAMECONTROLLERCONFIG` environment variable, which holds the same kind of line.

## Paths

The game reads all its files straight from your ISO. It finds the ISO in this order:

1. `--iso FILE` on the command line, or `iso = FILE` in `ctw.ini`
2. on Linux, the image given to `setup.sh` (its path is built into the executable)
3. the first `*.iso` next to the executable, then in the working directory

Other paths, which you rarely need:

| Flag | Default | Contents |
|---|---|---|
| `--image FILE` | Linux: `<repo>/build/gen/image.bin`; Windows: next to `ctw.exe` | initial memory image of the recompiled game |
| `--assets DIR` | Linux: `<repo>/runtime/assets`; Windows: `assets\` next to `ctw.exe` | runtime data (VFPU tables) |
| `--ms DIR` | `ms0` in the working directory (`run/ms0`, or next to `ctw.exe` on Windows) | the memory stick (`ms0:`) |
| `--umd DIR` | none | read the game files from an extracted UMD (`setup.sh --extract-all`) instead of the ISO |

### Saves

Saves are stored on the virtual memory stick, in the same layout as on a PSP (Linux: `run/ms0`,
Windows: `ms0\` next to `ctw.exe`):

```
ms0/PSP/SAVEDATA/ULUS10491001/
    DATA.BIN  PARAM.SFO  ICON0.PNG  ICON1.PMF
```

To back up your progress, copy that folder. These saves are **not encrypted**, so they can't yet be
copied to a real PSP or to PPSSPP, and saves from those can't be loaded either.

## Files written at run time

| File (in `run/`, or next to `ctw.exe` on Windows) | Contents |
|---|---|
| `ctw.log` | runtime log; it is overwritten on every start, so keep a copy when reporting a bug |
| `ms0/` | memory stick (saves) |
| `shot_NNN.ppm` | screenshots, only with `CTW_SHOT_EVERY` |

## Debugging environment variables

These are for development. A normal player never needs them.

| Variable | Example | Effect |
|---|---|---|
| `CTW_LOG` | `CTW_LOG=io,ge` | log only these channels: `kernel thread io display ge audio misc` (`rt` and `unimpl` are always on) |
| `CTW_FPS` | `CTW_FPS=2` | log fps and per-frame timings every 2 s |
| `CTW_DUMP_MEM` | `CTW_DUMP_MEM=1` | with `CTW_SHOT_EVERY`: user RAM (0x08800000, 24 MB) to `mem_NNN.bin` next to each screenshot |
| `CTW_WATCH` | `CTW_WATCH=08C1F604` | only in a build with `-DCMAKE_CXX_FLAGS=-DCTW_WATCH`: log the first stores to that address with a guest backtrace and call chain; `CTW_WATCH_AFTER=212` starts logging at 212 s |
| `CTW_SHOT_EVERY` | `CTW_SHOT_EVERY=5` | write a screenshot every 5 s |
| `CTW_INPUT` | `CTW_INPUT="16=start,20.5=cross+down,30=cross:1.0"` | scripted button presses: `seconds=buttons[:duration]` (buttons: `cross circle square triangle up down left right l r start select`, and `nup ndown nleft nright` for the analog nub, `f1` / `f3` for those keys) |
| `CTW_LOAD_STATE` | `CTW_LOAD_STATE=a.ctwstate` | load a savestate as soon as the game boots |
| `CTW_SAVE_STATE_AT` | `CTW_SAVE_STATE_AT=110` | save a state at 110 s (to `CTW_SAVE_STATE_FILE`, default the F5 slot) |
| `CTW_GETRACE_AT` | `CTW_GETRACE_AT=40` | dump one frame of GE commands at 40 s |
| `CTW_VBTRACE_AT` | `CTW_VBTRACE_AT=40` | timeline of vblanks, GE and waits around 40 s |
| `CTW_GE_THREADS` | `CTW_GE_THREADS=8` | rasteriser threads of the software renderer |

`--headless` runs without a window and without sound (for automated tests together with
`CTW_INPUT` and `CTW_SHOT_EVERY`).
