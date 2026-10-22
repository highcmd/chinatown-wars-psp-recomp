// Networking: the console has no Wi-Fi here. The libraries initialise, ad hoc
// scans find nobody, and connections fail, so multiplayer menus report that no
// other player was found.
#include <cstdio>
#include <cstring>

#include "kernel.h"

static const u8 kMac[6] = {0x02, 0x00, 0x48, 0x4D, 0x48, 0x01};   // locally administered

HLE(sceNet, sceNetInit) { RET(0); }
HLE(sceNet, sceNetTerm) { RET(0); }
HLE(sceNet, sceNetEtherNtostr) {
	char s[18];
	const u8 *m = gptr(ARG(0));
	snprintf(s, sizeof(s), "%02x:%02x:%02x:%02x:%02x:%02x", m[0], m[1], m[2], m[3], m[4], m[5]);
	memcpy(gptr(ARG(1)), s, 18);
	RET(0);
}
HLE(sceWlanDrv, sceWlanGetEtherAddr) {
	memcpy(gptr(ARG(0)), kMac, 6);
	RET(0);
}

enum : u32 {
	ADHOC_NOT_CONNECTED = 0x80410716,   // SCE_NET_ADHOC_ERROR_*: connection refused
	ADHOC_TIMEOUT = 0x80410715,
	ADHOCCTL_BUSY = 0x80410b10,
};

HLE(sceNetAdhoc, sceNetAdhocInit) { RET(0); }
HLE(sceNetAdhoc, sceNetAdhocTerm) { RET(0); }
HLE(sceNetAdhoc, sceNetAdhocPtpOpen) { RET(ADHOC_NOT_CONNECTED); }
HLE(sceNetAdhoc, sceNetAdhocPtpListen) { RET(ADHOC_NOT_CONNECTED); }
HLE(sceNetAdhoc, sceNetAdhocPtpAccept) { RET(ADHOC_TIMEOUT); }
HLE(sceNetAdhoc, sceNetAdhocPtpConnect) { RET(ADHOC_NOT_CONNECTED); }
HLE(sceNetAdhoc, sceNetAdhocPtpSend) { RET(ADHOC_NOT_CONNECTED); }
HLE(sceNetAdhoc, sceNetAdhocPtpRecv) { RET(ADHOC_TIMEOUT); }
HLE(sceNetAdhoc, sceNetAdhocPtpFlush) { RET(0); }
HLE(sceNetAdhoc, sceNetAdhocPtpClose) { RET(0); }

// sceNetAdhocctl: state 0 = disconnected; handlers are never called (no events).
HLE(sceNetAdhocctl, sceNetAdhocctlInit) { RET(0); }
HLE(sceNetAdhocctl, sceNetAdhocctlTerm) { RET(0); }
HLE(sceNetAdhocctl, sceNetAdhocctlAddHandler) { RET(0); }
HLE(sceNetAdhocctl, sceNetAdhocctlDelHandler) { RET(0); }
HLE(sceNetAdhocctl, sceNetAdhocctlGetState) {
	if (gvalid(ARG(0))) SW(ARG(0), 0);
	RET(0);
}
HLE(sceNetAdhocctl, sceNetAdhocctlScan) { RET(0); }
HLE(sceNetAdhocctl, sceNetAdhocctlDisconnect) { RET(0); }
HLE(sceNetAdhocctl, sceNetAdhocctlGetScanInfo) {
	if (gvalid(ARG(0))) SW(ARG(0), 0);   // buffer length used: no networks
	RET(0);
}
HLE(sceNetAdhocctl, sceNetAdhocctlGetPeerList) {
	if (gvalid(ARG(0))) SW(ARG(0), 0);
	RET(0);
}

HLE(sceNetAdhocMatching, sceNetAdhocMatchingInit) { RET(0); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingTerm) { RET(0); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingCreate) { RET(1); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingDelete) { RET(0); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingStart) { RET(0); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingStop) { RET(0); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingSelectTarget) { RET(ADHOC_NOT_CONNECTED); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingCancelTargetWithOpt) { RET(0); }
HLE(sceNetAdhocMatching, sceNetAdhocMatchingSendData) { RET(ADHOC_NOT_CONNECTED); }
