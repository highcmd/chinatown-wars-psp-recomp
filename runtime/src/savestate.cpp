// Savestates: quick save (F5) and quick load (F9), plus CTW_SAVE_STATE_AT / CTW_LOAD_STATE
// for test runs.
//
// A state is taken from the scheduler while every guest thread waits inside one system
// call (no thread running, no GE list in flight, no interrupt queued). It holds guest
// memory, every thread's registers and shadow call stack (recomp.h), and the HLE modules'
// objects. Host stacks are not saved, so a state survives rebuilding the executable:
// loading gives each waiting thread a new fiber that re-enters its recorded calls, guest
// address by guest address, and then makes the same system call again (a wait started
// afresh: timeouts restart, nothing else changes).
#include <cstdio>
#include <filesystem>
#include <string>
#include <vector>

#include "kernel.h"
#include "osd.h"
#include "platform.h"
#include "savestate.h"

u32 *g_ssp;
bool g_resuming;
u32 g_resume_tgt;

void misc_state(StateIO &s);
void savedata_state(StateIO &s);
std::string mpeg_save_blocker();
void rt_set_time_us(u64 t);

static const char MAGIC[8] = {'C', 'T', 'W', 'S', 'T', 'A', 'T', 'E'};
static const u32 VERSION = 1;

// Guest memory in the state: main RAM, VRAM, scratchpad. Pages of zeros are skipped.
static const struct { u32 lo, hi; } REGIONS[] = {
	{0x08000000, 0x0A000000}, {0x04000000, 0x04200000}, {0x00010000, 0x00014000}};
static const u32 PAGE = 0x1000;

// ---------------------------------------------------------------- resuming threads
static std::vector<u32> s_res;   // (call site, target) pairs, outermost first
static size_t s_res_pos;
static u32 s_res_func;           // the function that must ask for the next site

void savestate_begin_resume(std::vector<u32> &&sites, u32 entry) {
	s_res = std::move(sites);
	s_res_pos = 0;
	s_res_func = entry & 0x3FFFFFFF;
	g_resuming = !s_res.empty();
}

u32 rt_resume_site(u32 func) {
	func &= 0x3FFFFFFF;
	if (s_res_pos + 2 > s_res.size() || func != s_res_func) {
		rt_log_error("savestate: cannot resume: function %08x asked for a call site, expected %08x (step %zu of %zu)",
		             func, s_res_func, s_res_pos / 2, s_res.size() / 2);
		kernel_request_exit();
	}
	u32 site = s_res[s_res_pos], tgt = s_res[s_res_pos + 1];
	s_res_pos += 2;
	g_resume_tgt = tgt;
	s_res_func = tgt & 0x3FFFFFFF;
	if (s_res_pos >= s_res.size()) g_resuming = false;
	return site;
}

// ---------------------------------------------------------------- the state
static void memory_io(StateIO &s) {
	s.tag("MEM ");
	for (auto &r : REGIONS) {
		for (u32 a = r.lo; a < r.hi && !s.bad; a += PAGE) {
			u8 *p = gptr(a);
			u8 nonzero = 0;
			if (s.saving)
				for (u32 i = 0; i < PAGE; i += 8) {
					u64 v;
					memcpy(&v, p + i, 8);
					if (v) { nonzero = 1; break; }
				}
			s.pod(nonzero);
			if (nonzero) s.raw(p, PAGE);
			else if (!s.saving) memset(p, 0, PAGE);
		}
	}
}

static void all_state(StateIO &s) {
	memory_io(s);
	kernel_thread_state(s);
	kernel_misc_state(s);
	io_state(s);
	audio_state(s);
	intr_state(s);
	display_state(s);
	ge_state(s);
	ge_render_state(s);
	misc_state(s);
	savedata_state(s);
	s.tag("END ");
}

static std::string blocker() {
	std::string b = kernel_thread_save_blocker();
	if (b.empty()) b = mpeg_save_blocker();
	if (b.empty() && !ge_idle()) b = "the GE is drawing";
	return b;
}

static bool save_to(const std::string &path) {
	StateIO s(true);
	s.raw((void *)MAGIC, 8);
	u32 ver = VERSION;
	s.pod(ver);
	u64 now = rt_time_us();
	s.pod(now);
	all_state(s);
	std::error_code ec;
	std::filesystem::create_directories(u8p(path).parent_path(), ec);
	std::string tmp = path + ".tmp";
	FILE *f = fopen(tmp.c_str(), "wb");
	if (!f) return false;
	bool ok = fwrite(s.buf.data(), 1, s.buf.size(), f) == s.buf.size();
	ok = fclose(f) == 0 && ok;
	if (ok) {
		std::filesystem::rename(u8p(tmp), u8p(path), ec);
		ok = !ec;
	}
	rt_log(LOG_RT, "savestate: saved %s (%zu KB)%s", path.c_str(), s.buf.size() / 1024, ok ? "" : " FAILED");
	return ok;
}

static bool load_from(const std::string &path, std::string &why) {
	FILE *f = fopen(path.c_str(), "rb");
	if (!f) { why = "no state in " + path; return false; }
	StateIO s(false);
	fseeko(f, 0, SEEK_END);
	s.buf.resize((size_t)ftello(f));
	fseeko(f, 0, SEEK_SET);
	bool ok = fread(s.buf.data(), 1, s.buf.size(), f) == s.buf.size();
	fclose(f);
	char magic[8];
	u32 ver = 0;
	s.raw(magic, 8);
	s.pod(ver);
	if (!ok || memcmp(magic, MAGIC, 8) || ver != VERSION) { why = path + " is not a state of this version"; return false; }
	u64 when;
	s.pod(when);
	// From here on the running game is replaced: a failure can only end it.
	rt_set_time_us(when);
	all_state(s);
	if (s.bad) {
		rt_log_error("savestate: loading %s failed: %s", path.c_str(), s.error.c_str());
		kernel_request_exit();
	}
	rt_log(LOG_RT, "savestate: loaded %s", path.c_str());
	return true;
}

// ---------------------------------------------------------------- requests
enum Req { NONE, SAVE, LOAD };
static Req s_req;
static std::string s_path;
static u64 s_req_since;

static std::string slot_path(int slot) { return "savestates/quick" + std::to_string(slot) + ".ctwstate"; }

void savestate_request_save(int slot) { s_req = SAVE; s_path = slot_path(slot); s_req_since = rt_time_us(); }
void savestate_request_load(int slot) { s_req = LOAD; s_path = slot_path(slot); s_req_since = rt_time_us(); }
void savestate_request_load_file(const std::string &path) { s_req = LOAD; s_path = path; s_req_since = rt_time_us(); }

bool savestate_pending() {
	static bool envDone;
	if (!envDone) {
		envDone = true;
		if (const char *p = getenv("CTW_LOAD_STATE")) savestate_request_load_file(p);
	}
	static double saveAt = getenv("CTW_SAVE_STATE_AT") ? atof(getenv("CTW_SAVE_STATE_AT")) : -1;
	if (saveAt >= 0 && rt_time_us() / 1e6 >= saveAt && s_req == NONE) {
		saveAt = -1;
		s_req = SAVE;
		s_path = getenv("CTW_SAVE_STATE_FILE") ? getenv("CTW_SAVE_STATE_FILE") : slot_path(1);
		s_req_since = rt_time_us();
	}
	return s_req != NONE;
}

void savestate_service() {
	if (s_req == SAVE) {
		std::string b = blocker();
		if (!b.empty()) {
			if (rt_time_us() - s_req_since > 3000000) {   // never a quiet moment: give up
				rt_log(LOG_RT, "savestate: cannot save now: %s", b.c_str());
				osd_message("CANNOT SAVE NOW");
				s_req = NONE;
			}
			return;
		}
		s_req = NONE;
		osd_message(save_to(s_path) ? "STATE SAVED" : "SAVING THE STATE FAILED");
	} else if (s_req == LOAD) {
		if (!ge_idle()) return;
		s_req = NONE;
		std::string why;
		if (load_from(s_path, why)) {
			osd_message("STATE LOADED");
		} else {
			rt_log(LOG_RT, "savestate: %s", why.c_str());
			osd_message("NO STATE TO LOAD");
		}
	}
}
