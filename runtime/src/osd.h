#pragma once
// On-screen text (FPS meter, hotkey messages); see osd.cpp.
#include <vector>
#include <cstdint>

extern bool g_osd_fps;                        // F2
void osd_message(const char *fmt, ...);       // shown for 2 s under the FPS meter
void osd_on_vblank();                         // updates the FPS figure
// The text box as RGBA pixels (top row first); false when there is nothing to show.
bool osd_build(std::vector<uint32_t> &px, int &w, int &h);
// Draws the box into the top-left corner of an RGBA picture, each pixel scale x scale.
void osd_blit(uint32_t *dst, int dw, int dh, int scale);
