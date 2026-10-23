// Hooks on specific Chinatown Wars functions (see data/hooks.json): a hook named
// in hooks.json replaces F_<addr> and gets the original as `orig`.
//
// Cheats (data/cheats.json): instructions patched in the generated code, switched by a
// bit of g_cheats at run time.
#include "recomp.h"
#include "settings.h"

u32 g_cheats;

// Streamed city (data/hooks.json: F_089F4754, the streaming manager's update). The game keeps
// a 3x3 grid of 60-unit tiles around the point where the camera looks at the ground, at most
// 64 units ahead. The third-person camera looks level, has no such point, and the game centres
// on the camera itself: half the grid behind it, the city ending 60-120 units ahead. While the
// camera looks level the update sees the camera one tile (60 units) further along the view,
// as with the top-down camera; the city then reaches 120-180 units ahead. (A 5x5 grid was
// tried: the world data keeps object indices apart only for 2x2 sector files, see NOTES.md.)
void tpcam_stream_ahead(CPUState *c, RecompFunc orig) {
	u32 cam = LW(0x08B542E0);
	if (!(g_cheats & 1u) || !cam || LW(cam + 0xFCu)) { orig(c); return; }
	s32 x = (s32)LW(cam + 0x100u), y = (s32)LW(cam + 0x104u);
	// +0xF4/+0xF8: the view direction negated, 20.12 fixed point
	SW(cam + 0x100u, (u32)(x - (s32)LW(cam + 0xF4u) * 60));
	SW(cam + 0x104u, (u32)(y - (s32)LW(cam + 0xF8u) * 60));
	orig(c);
	SW(cam + 0x100u, (u32)x);
	SW(cam + 0x104u, (u32)y);
}

// Third-person camera (bit 0, F1). The game keeps its camera height at +0x108 of the
// camera object and pitches the view by the angle at +0x12C. The patched stores of
// the height are skipped; this replaces `lh a0, 0x12C(s0)` in the view-matrix builder
// (F_088559AC, s0 = camera, runs every frame): pitch 0 and the height held.
void cheat_tpcam_pitch(CPUState *c) {
	static bool was_on;
	u32 cam = c->r[16];
	if (g_cheats & 1u) {
		c->r[4] = 0;
		SW(cam + 0x108u, (u32)g_settings.cameraHeight);
		was_on = true;
		return;
	}
	if (was_on) {   // back to the game's camera height; its own updates take over from here
		SW(cam + 0x108u, 111700u);
		was_on = false;
	}
	c->r[4] = (u32)(s32)(s16)LH(cam + 0x12Cu);
}
