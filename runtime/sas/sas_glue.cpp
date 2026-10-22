// sceSasCore HLE on top of the PPSSPP SAS mixer (SasAudio.cpp). Argument checks and
// error codes follow PPSSPP's sceSas.cpp. The mix runs synchronously in __sceSasCore.
#include <cstdlib>

#include "sas_shim.h"
#include "SasAudio.h"

enum : u32 {
	SAS_ERROR_INVALID_GRAIN = 0x80420001,
	SAS_ERROR_INVALID_MAX_VOICES = 0x80420002,
	SAS_ERROR_INVALID_OUTPUT_MODE = 0x80420003,
	SAS_ERROR_INVALID_SAMPLE_RATE = 0x80420004,
	SAS_ERROR_BAD_ADDRESS = 0x80420005,
	SAS_ERROR_INVALID_VOICE = 0x80420010,
	SAS_ERROR_INVALID_NOISE_FREQ = 0x80420011,
	SAS_ERROR_INVALID_PITCH = 0x80420012,
	SAS_ERROR_INVALID_ADSR_CURVE_MODE = 0x80420013,
	SAS_ERROR_INVALID_PARAMETER = 0x80420014,
	SAS_ERROR_INVALID_LOOP_POS = 0x80420015,
	SAS_ERROR_VOICE_PAUSED = 0x80420016,
	SAS_ERROR_INVALID_VOLUME = 0x80420018,
	SAS_ERROR_INVALID_ADSR_RATE = 0x80420019,
	SAS_ERROR_INVALID_PCM_SIZE = 0x8042001A,
	SAS_ERROR_REV_INVALID_TYPE = 0x80420020,
	SAS_ERROR_REV_INVALID_FEEDBACK = 0x80420021,
	SAS_ERROR_REV_INVALID_DELAY = 0x80420022,
	SAS_ERROR_REV_INVALID_VOLUME = 0x80420023,
};

// ATRAC3 voices are not supported (no game here uses them).
int SasAtrac3::SetContext(u32) { return -1; }
void SasAtrac3::GetNextSamples(s16 *out, int n) { memset(out, 0, n * sizeof(s16)); }
int SasAtrac3::Concatenate(u32, u32) { return -1; }

static SasInstance *s_sas = new SasInstance();

static bool bad_voice(int v) { return v < 0 || v >= PSP_SAS_VOICES_MAX; }

HLE(sceSasCore, __sceSasInit) {
	u32 core = ARG(0), grain = ARG(1), maxVoices = ARG(2), outMode = ARG(3), rate = ARG(4);
	rt_log(LOG_AUDIO, "SasInit(core %08x, grain %u, voices %u, outmode %u, rate %u)", core, grain, maxVoices, outMode, rate);
	if (!gvalid(core) || (core & 0x3F)) { RET(SAS_ERROR_BAD_ADDRESS); return; }
	if (maxVoices == 0 || maxVoices > PSP_SAS_VOICES_MAX) { RET(SAS_ERROR_INVALID_MAX_VOICES); return; }
	if (grain < 0x40 || grain > 0x800 || (grain & 0x1F)) { RET(SAS_ERROR_INVALID_GRAIN); return; }
	if (outMode > 1) { RET(SAS_ERROR_INVALID_OUTPUT_MODE); return; }
	if (rate != 44100) { RET(SAS_ERROR_INVALID_SAMPLE_RATE); return; }
	s_sas->SetGrainSize(grain);
	s_sas->maxVoices = PSP_SAS_VOICES_MAX;
	s_sas->outputMode = outMode;
	for (auto &v : s_sas->voices) {
		v.sampleRate = rate;
		v.playing = false;
		v.loop = false;
	}
	RET(0);
}

HLE(sceSasCore, __sceSasCore) {
	if (!gvalid(ARG(1))) { RET(SAS_ERROR_INVALID_PARAMETER); return; }
	s_sas->Mix(ARG(1), 0, 0, 0, false);
	RET(0);
}

HLE(sceSasCore, __sceSasCoreWithMix) {
	if (!gvalid(ARG(1))) { RET(SAS_ERROR_INVALID_PARAMETER); return; }
	s_sas->Mix(ARG(1), ARG(1), (int)ARG(2), (int)ARG(3), false);
	RET(0);
}

HLE(sceSasCore, __sceSasGetEndFlag) {
	u32 f = 0;
	for (int i = 0; i < s_sas->maxVoices; i++)
		if (!s_sas->voices[i].playing) f |= 1u << i;
	RET(f);
}

HLE(sceSasCore, __sceSasSetVoice) {
	int vn = (int)ARG(1), size = (int)ARG(3), loop = (int)ARG(4);
	u32 vag = ARG(2);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	if (size == 0 || ((u32)size & 0xF)) { RET(SAS_ERROR_INVALID_PARAMETER); return; }
	if (loop != 0 && loop != 1) { RET(SAS_ERROR_INVALID_LOOP_POS); return; }
	if (!gvalid(vag)) { RET(0); return; }
	if (size < 0) size = 0;   // accepted, but plays nothing
	SasVoice &v = s_sas->voices[vn];
	bool reset = v.type != VOICETYPE_VAG || v.vagAddr != vag || v.vagSize != size || v.loop != (loop != 0);
	v.type = VOICETYPE_VAG;
	v.vagAddr = vag;
	v.vagSize = size;
	v.loop = loop != 0;
	if (v.on) v.playing = true;
	if (reset) v.vag.Start(vag, size, loop != 0);
	RET(0);
}

HLE(sceSasCore, __sceSasSetVoicePCM) {
	int vn = (int)ARG(1), size = (int)ARG(3), loopPos = (int)ARG(4);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	if (size <= 0 || size > 0x10000) { RET(SAS_ERROR_INVALID_PCM_SIZE); return; }
	if (loopPos >= size) { RET(SAS_ERROR_INVALID_LOOP_POS); return; }
	if (!gvalid(ARG(2))) { RET(0); return; }
	SasVoice &v = s_sas->voices[vn];
	v.type = VOICETYPE_PCM;
	v.pcmAddr = ARG(2);
	v.pcmSize = size;
	v.pcmIndex = 0;
	v.pcmLoopPos = loopPos >= 0 ? loopPos : 0;
	v.loop = loopPos >= 0;
	v.playing = true;
	RET(0);
}

HLE(sceSasCore, __sceSasGetPauseFlag) {
	u32 f = 0;
	for (int i = 0; i < s_sas->maxVoices; i++)
		if (s_sas->voices[i].paused) f |= 1u << i;
	RET(f);
}

HLE(sceSasCore, __sceSasSetPause) {
	u32 bits = ARG(1);
	for (int i = 0; bits && i < PSP_SAS_VOICES_MAX; i++, bits >>= 1)
		if (bits & 1) s_sas->voices[i].paused = ARG(2) != 0;
	RET(0);
}

HLE(sceSasCore, __sceSasSetVolume) {
	int vn = (int)ARG(1), l = (int)ARG(2), r = (int)ARG(3), el = (int)ARG(4), er = (int)ARG(5);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	if (abs(l) > PSP_SAS_VOL_MAX || abs(r) > PSP_SAS_VOL_MAX || abs(el) > PSP_SAS_VOL_MAX || abs(er) > PSP_SAS_VOL_MAX) {
		RET(SAS_ERROR_INVALID_VOLUME);
		return;
	}
	SasVoice &v = s_sas->voices[vn];
	v.volumeLeft = l;
	v.volumeRight = r;
	v.effectLeft = el;
	v.effectRight = er;
	RET(0);
}

HLE(sceSasCore, __sceSasSetPitch) {
	int vn = (int)ARG(1), pitch = (int)ARG(2);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	if (pitch < PSP_SAS_PITCH_MIN || pitch > PSP_SAS_PITCH_MAX) { RET(SAS_ERROR_INVALID_PITCH); return; }
	s_sas->voices[vn].pitch = pitch;
	RET(0);
}

HLE(sceSasCore, __sceSasSetKeyOn) {
	int vn = (int)ARG(1);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	SasVoice &v = s_sas->voices[vn];
	if (v.paused || v.on) { RET(SAS_ERROR_VOICE_PAUSED); return; }
	v.KeyOn();
	RET(0);
}

HLE(sceSasCore, __sceSasSetKeyOff) {
	int vn = (int)ARG(1);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	SasVoice &v = s_sas->voices[vn];
	if (v.paused || !v.on) { RET(SAS_ERROR_VOICE_PAUSED); return; }
	v.KeyOff();
	RET(0);
}

HLE(sceSasCore, __sceSasSetNoise) {
	int vn = (int)ARG(1), freq = (int)ARG(2);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	if (freq < 0 || freq >= 64) { RET(SAS_ERROR_INVALID_NOISE_FREQ); return; }
	s_sas->voices[vn].type = VOICETYPE_NOISE;
	s_sas->voices[vn].noiseFreq = freq;
	RET(0);
}

HLE(sceSasCore, __sceSasSetSL) {
	int vn = (int)ARG(1);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	s_sas->voices[vn].envelope.SetSustainLevel((int)ARG(2));
	RET(0);
}

HLE(sceSasCore, __sceSasSetADSR) {
	int vn = (int)ARG(1), flag = (int)ARG(2), a = (int)ARG(3), d = (int)ARG(4), s = (int)ARG(5), r = (int)ARG(6);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	int invalid = (a < 0 ? 1 : 0) | (d < 0 ? 2 : 0) | (s < 0 ? 4 : 0) | (r < 0 ? 8 : 0);
	if (invalid & flag) { RET(SAS_ERROR_INVALID_ADSR_RATE); return; }
	s_sas->voices[vn].envelope.SetRate(flag, a, d, s, r);
	RET(0);
}

HLE(sceSasCore, __sceSasSetADSRmode) {
	int vn = (int)ARG(1), flag = (int)ARG(2);
	int a = (int)(ARG(3) & ~0x80000000u), d = (int)(ARG(4) & ~0x80000000u);
	int s = (int)(ARG(5) & ~0x80000000u), r = (int)(ARG(6) & ~0x80000000u);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	int invalid = ((a > 5 || (a & 1)) ? 1 : 0) | ((d > 5 || !(d & 1)) ? 2 : 0) | (s > 5 ? 4 : 0) | ((r > 5 || !(r & 1)) ? 8 : 0);
	if (invalid & flag) { RET(SAS_ERROR_INVALID_ADSR_CURVE_MODE); return; }
	s_sas->voices[vn].envelope.SetEnvelope(flag, a, d, s, r);
	RET(0);
}

HLE(sceSasCore, __sceSasSetSimpleADSR) {
	int vn = (int)ARG(1);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	if ((ARG(3) >> 13) & 1) { RET(SAS_ERROR_INVALID_ADSR_CURVE_MODE); return; }
	s_sas->voices[vn].envelope.SetSimpleEnvelope(ARG(2) & 0xFFFF, ARG(3) & 0xFFFF);
	RET(0);
}

HLE(sceSasCore, __sceSasGetEnvelopeHeight) {
	int vn = (int)ARG(1);
	if (bad_voice(vn)) { RET(SAS_ERROR_INVALID_VOICE); return; }
	RET(s_sas->voices[vn].envelope.GetHeight());
}

HLE(sceSasCore, __sceSasGetAllEnvelopeHeights) {
	u32 out = ARG(1);
	if (!gvalid(out)) { RET(SAS_ERROR_INVALID_PARAMETER); return; }
	for (int i = 0; i < PSP_SAS_VOICES_MAX; i++) SW(out + 4 * i, (u32)s_sas->voices[i].envelope.GetHeight());
	RET(0);
}

HLE(sceSasCore, __sceSasRevType) {
	int t = (int)ARG(1);
	if (t < PSP_SAS_EFFECT_TYPE_OFF || t > PSP_SAS_EFFECT_TYPE_MAX) { RET(SAS_ERROR_REV_INVALID_TYPE); return; }
	s_sas->SetWaveformEffectType(t);
	RET(0);
}

HLE(sceSasCore, __sceSasRevParam) {
	int delay = (int)ARG(1), fb = (int)ARG(2);
	if (delay < 0 || delay >= 128) { RET(SAS_ERROR_REV_INVALID_DELAY); return; }
	if (fb < 0 || fb >= 128) { RET(SAS_ERROR_REV_INVALID_FEEDBACK); return; }
	s_sas->waveformEffect.delay = delay;
	s_sas->waveformEffect.feedback = fb;
	RET(0);
}

HLE(sceSasCore, __sceSasRevEVOL) {
	if (ARG(1) > 0x1000 || ARG(2) > 0x1000) { RET(SAS_ERROR_REV_INVALID_VOLUME); return; }
	s_sas->waveformEffect.leftVol = ARG(1);
	s_sas->waveformEffect.rightVol = ARG(2);
	RET(0);
}

HLE(sceSasCore, __sceSasRevVON) {
	s_sas->waveformEffect.isDryOn = ARG(1) != 0;
	s_sas->waveformEffect.isWetOn = ARG(2) != 0;
	RET(0);
}

HLE(sceSasCore, __sceSasGetGrain) { RET(s_sas->GetGrainSize()); }
HLE(sceSasCore, __sceSasSetGrain) {
	s_sas->SetGrainSize((int)ARG(1));
	RET(0);
}
HLE(sceSasCore, __sceSasGetOutputmode) { RET(s_sas->outputMode); }
HLE(sceSasCore, __sceSasSetOutputmode) {
	if (ARG(1) > 1) { RET(SAS_ERROR_INVALID_OUTPUT_MODE); return; }
	s_sas->outputMode = ARG(1);
	RET(0);
}
