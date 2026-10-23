// Hooks on specific Chinatown Wars functions (see data/hooks.json): a hook named
// in hooks.json replaces F_<addr> and gets the original as `orig`. None are needed yet.
//
// Cheats (data/cheats.json): instructions patched in the generated code, switched by a
// bit of g_cheats at run time.
#include "recomp.h"
#include "settings.h"

u32 g_cheats;

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
