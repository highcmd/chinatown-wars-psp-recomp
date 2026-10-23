#pragma once
// Savestates (quick save F5 / quick load F9): see savestate.cpp.
#include <cstdint>
#include <cstring>
#include <deque>
#include <map>
#include <string>
#include <type_traits>
#include <utility>
#include <vector>

// One stream for both directions: each module describes its state once, with the same
// calls for saving and loading.
struct StateIO {
	bool saving;
	std::vector<uint8_t> buf;
	size_t pos = 0;
	bool bad = false;
	std::string error;

	explicit StateIO(bool save) : saving(save) {}

	void raw(void *p, size_t n) {
		if (saving) {
			const uint8_t *b = (const uint8_t *)p;
			buf.insert(buf.end(), b, b + n);
		} else if (pos + n > buf.size()) {
			fail("state file is truncated");
			memset(p, 0, n);
		} else {
			memcpy(p, buf.data() + pos, n);
			pos += n;
		}
	}
	template <class T> void pod(T &v) {
		static_assert(std::is_trivially_copyable<T>::value, "pod() needs a plain type");
		raw(&v, sizeof(T));
	}
	template <class A, class B> void pod(std::pair<A, B> &v) { pod(v.first); pod(v.second); }
	template <class T, size_t N> void arr(T (&v)[N]) { raw(v, sizeof(v)); }
	void str(std::string &s) {
		uint32_t n = (uint32_t)s.size();
		pod(n);
		if (!saving) s.resize(bad ? 0 : n);
		if (n && !bad) raw(&s[0], n);
	}
	template <class T> void vec(std::vector<T> &v) {
		uint32_t n = (uint32_t)v.size();
		pod(n);
		if (!saving) v.resize(bad ? 0 : n);
		if (n && !bad) raw(v.data(), n * sizeof(T));
	}
	void bools(std::vector<bool> &v) {
		uint32_t n = (uint32_t)v.size();
		pod(n);
		if (!saving) v.assign(bad ? 0 : n, false);
		for (uint32_t i = 0; i < n && !bad; i++) {
			uint8_t b = v[i];
			pod(b);
			v[i] = b;
		}
	}
	template <class T> void deq(std::deque<T> &v) {
		std::vector<T> tmp(v.begin(), v.end());
		vec(tmp);
		if (!saving) v.assign(tmp.begin(), tmp.end());
	}
	// map<K, V> with a per-value function f(StateIO&, V&)
	template <class K, class V, class F> void map(std::map<K, V> &m, F f) {
		uint32_t n = (uint32_t)m.size();
		pod(n);
		if (saving) {
			for (auto &[k, v] : m) {
				K key = k;
				pod(key);
				f(*this, v);
			}
		} else {
			m.clear();
			for (uint32_t i = 0; i < n && !bad; i++) {
				K key{};
				pod(key);
				f(*this, m[key]);
			}
		}
	}
	// a 4-character marker between sections, so a mismatch is reported where it starts
	void tag(const char *t) {
		uint32_t v;
		memcpy(&v, t, 4);
		uint32_t got = v;
		pod(got);
		if (!saving && got != v && !bad) fail(std::string("state file section '") + t + "' does not match");
	}
	void fail(const std::string &why) {
		if (!bad) error = why;
		bad = true;
	}
};

// Per-module state (each in its own .cpp, which owns the statics).
void kernel_thread_state(StateIO &s);   // threads, kernel objects, timers
void kernel_misc_state(StateIO &s);     // memory blocks, callbacks ids
void io_state(StateIO &s);
void audio_state(StateIO &s);
void intr_state(StateIO &s);
void display_state(StateIO &s);
void ge_state(StateIO &s);
void ge_render_state(StateIO &s);

// Why a state cannot be taken right now ("" = it can); checked by the modules.
std::string kernel_thread_save_blocker();
std::string hle_save_blocker();
bool ge_idle();

// Hotkeys and --load-state / --save-state-at.
void savestate_request_save(int slot);
void savestate_request_load(int slot);
void savestate_request_load_file(const std::string &path);
bool savestate_pending();
void savestate_service();   // scheduler, while every thread waits
