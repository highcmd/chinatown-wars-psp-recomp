// Smaller HLE functions: module manager, sysmem, DMAC, impose, display rate, UMD
// waits, utility modules, MPEG decoder control.
#include <cstring>

#include "kernel.h"

HLE(ModuleMgrForUser, sceKernelGetModuleIdByAddress) { RET(0x1000); }
HLE(ModuleMgrForUser, sceKernelGetModuleId) { RET(0x1000); }
HLE(ModuleMgrForUser, sceKernelStopUnloadSelfModuleWithStatus) {
	LOGK("StopUnloadSelfModuleWithStatus(%x): the game quits", ARG(0));
	kernel_request_exit();
	kernel_wait(WAIT_HLE, 0xDEAD, 0, false);
}

HLE(SysMemUserForUser, sceKernelSetCompiledSdkVersion500_505) { RET(0); }
HLE(SysMemUserForUser, sceKernelSetCompilerVersion) { RET(0); }
HLE(SysMemUserForUser, sceKernelPrintf) {
	rt_log(LOG_MISC, "guest printf: %s", gstr(ARG(0)).c_str());
	RET(0);
}

HLE(sceDmac, sceDmacMemcpy) {
	u32 dst = ARG(0), src = ARG(1), n = ARG(2);
	if (n && gvalid(dst) && gvalid(src) && gvalid(dst + n - 1) && gvalid(src + n - 1))
		memmove(gptr(dst), gptr(src), n);
	RET(0);
}

HLE(sceImpose, sceImposeSetLanguageMode) { RET(0); }

HLE(sceDisplay, sceDisplayGetFramePerSec) {
	c->f[0] = 59.9400599f;
	RET(0);
}

// The UMD is always in and ready: waits return at once.
HLE(sceUmdUser, sceUmdWaitDriveStat) { RET(0); }
HLE(sceUmdUser, sceUmdWaitDriveStatCB) { RET(0); }
HLE(sceUmdUser, sceUmdCancelWaitDriveStat) { RET(0); }

// Optional system modules (network, codecs): their functions are HLE'd already.
HLE(sceUtility, sceUtilityLoadModule) {
	LOGK("UtilityLoadModule(%x)", ARG(0));
	RET(0);
}
HLE(sceUtility, sceUtilityUnloadModule) { RET(0); }

HLE(sceMpeg, sceMpegAvcDecodeFlush) { RET(0); }
HLE(sceMpeg, sceMpegAvcDecodeStop) {
	if (ARG(3)) SW(ARG(3), 0);   // no frame left in the decoder
	RET(0);
}
