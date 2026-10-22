#define CTW_GL_NO_MACROS
#include "gl_funcs.h"

#include <SDL2/SDL.h>
#include <cstdio>

#define CTW_GL_DEFINE(type, name) type ssx_##name;
CTW_GL_FUNCS(CTW_GL_DEFINE)
#undef CTW_GL_DEFINE

bool gl_load_functions() {
	bool ok = true;
#define CTW_GL_LOAD(type, name)                                                  \
	ssx_##name = (type)SDL_GL_GetProcAddress(#name);                             \
	if (!ssx_##name) { fprintf(stderr, "GL: missing %s\n", #name); ok = false; }
	CTW_GL_FUNCS(CTW_GL_LOAD)
#undef CTW_GL_LOAD
	return ok;
}
