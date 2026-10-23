#pragma once
// User settings: ctw.ini (key = value) in the working directory, overridden by CLI flags.
#include <map>
#include <string>

struct Settings {
	int fps = 30;              // 30 = the game's rate; 60 = in-between frames (GL renderer)
	int width = 960;           // window size (output resolution)
	int height = 544;
	int renderScale = 0;
	std::string renderer = "gl";   // gl (GPU) or software       // internal resolution = 480x272 * scale; 0 = match the window height
	bool fullscreen = false;   // borderless desktop fullscreen, or exclusive with refresh > 0
	int refresh = 0;           // exclusive fullscreen at resolution @ refresh Hz; 0 = keep the desktop mode
	bool linear = true;        // scaling filter: linear (smooth) or nearest (sharp pixels)
	bool vsync = false;        // host vsync on present
	int deadzone = 8000;       // gamepad stick deadzone (0..32767)
	bool rightStickAsDpad = false;
	std::string padMapping;    // optional SDL_GameControllerDB line
	bool showFps = false;      // FPS meter at start (F2 toggles)
	bool thirdPerson = false;  // start with the third-person camera cheat on (F1 toggles)
	int cameraHeight = 15000;  // its camera height (game units; the game's own is ~111700)
	std::string isoPath;       // UMD image (ctw.ini 'iso'; --iso on the command line)
	// Input bindings: "key_cross" -> "Z" (SDL scancode names), "pad_cross" -> "a" (SDL
	// game controller button names, plus lefttrigger/righttrigger). Comma = several.
	std::map<std::string, std::string> bindings;
};

extern Settings g_settings;
int settings_render_scale();   // resolved scale (1..6)
void settings_load(const char *path);
// Returns false on an unknown option; i is advanced past consumed arguments.
bool settings_parse_arg(int argc, char **argv, int &i);
const char *settings_usage();
