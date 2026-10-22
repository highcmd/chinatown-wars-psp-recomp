// prxdecrypt: decrypt a PSP ~PSP executable (EBOOT.BIN / .prx) from the user's own
// UMD image into the plain (possibly gzip-compressed) module, using PPSSPP's
// PrxDecrypter and libkirk. Output: the decrypted bytes, exactly as the PSP's loader sees them.
//   prxdecrypt <in ~PSP file> <out file>
#include <cstdio>
#include <cstring>
#include <vector>

#include "Core/ELF/PrxDecrypter.h"

int main(int argc, char **argv) {
	if (argc != 3) {
		fprintf(stderr, "usage: prxdecrypt <in ~PSP file> <out file>\n");
		return 2;
	}
	FILE *f = fopen(argv[1], "rb");
	if (!f) { perror(argv[1]); return 1; }
	std::vector<unsigned char> in;
	unsigned char buf[65536];
	size_t n;
	while ((n = fread(buf, 1, sizeof(buf), f)) > 0) in.insert(in.end(), buf, buf + n);
	fclose(f);
	if (in.size() < 0x150 || memcmp(in.data(), "~PSP", 4) != 0) {
		fprintf(stderr, "%s is not an encrypted PSP module (~PSP)\n", argv[1]);
		return 1;
	}
	std::vector<unsigned char> out(in.size() + 0x100);
	int size = pspDecryptPRX(in.data(), out.data(), (u32)in.size());
	if (size <= 0) {
		fprintf(stderr, "decryption failed (unknown tag %08x)\n", *(u32 *)&in[0xD0]);
		return 1;
	}
	FILE *o = fopen(argv[2], "wb");
	if (!o || fwrite(out.data(), 1, size, o) != (size_t)size || fclose(o) != 0) { perror(argv[2]); return 1; }
	printf("decrypted %d bytes\n", size);
	return 0;
}
