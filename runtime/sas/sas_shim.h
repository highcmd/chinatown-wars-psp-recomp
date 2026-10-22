#pragma once
// What the PPSSPP SAS sources expect from PPSSPP, mapped onto this runtime.
#include <algorithm>
#include <cstdint>
#include <cstring>

#include "Common/CommonTypes.h"
#include "hle.h"

namespace Memory {
inline bool IsValidAddress(u32 a) { return gvalid(a); }
inline bool IsValidRange(u32 a, u32 n) { return gvalid(a) && (n == 0 || gvalid(a + n - 1)); }
inline u8 *GetPointerUnchecked(u32 a) { return gptr(a); }
inline u8 *GetPointerWriteRange(u32 a, u32 n) { return IsValidRange(a, n) ? gptr(a) : nullptr; }
inline const u8 *GetPointerRange(u32 a, u32 n) { return IsValidRange(a, n) ? gptr(a) : nullptr; }
inline void Memcpy(void *dst, u32 src, u32 n, const char * = nullptr) {
	if (IsValidRange(src, n)) memcpy(dst, gptr(src), n);
}
inline void Write_U32(u32 v, u32 a) { SW(a, v); }
}  // namespace Memory

static inline s16 clamp_s16(int v) { return (s16)std::clamp(v, -32768, 32767); }

#ifndef ARRAY_SIZE
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#endif
#define PROFILE_THIS_SCOPE(x)
#define _dbg_assert_(x) ((void)0)
#define ERROR_LOG(cat, ...) rt_log_error(__VA_ARGS__)
#define WARN_LOG(cat, ...) rt_log(LOG_AUDIO, __VA_ARGS__)
#define INFO_LOG(cat, ...) ((void)0)
#define DEBUG_LOG(cat, ...) ((void)0)
#define VERBOSE_LOG(cat, ...) ((void)0)
#define WARN_LOG_REPORT(cat, ...) rt_log(LOG_AUDIO, __VA_ARGS__)
#define WARN_LOG_REPORT_ONCE(id, cat, ...) do { static bool id##_once; if (!id##_once) { id##_once = true; rt_log(LOG_AUDIO, __VA_ARGS__); } } while (0)
#define ERROR_LOG_REPORT(cat, ...) rt_log_error(__VA_ARGS__)
enum class MemBlockFlags { READ, WRITE };
static inline bool MemBlockInfoDetailed() { return false; }
static inline void NotifyMemInfo(MemBlockFlags, u32, u32, const char *) {}
