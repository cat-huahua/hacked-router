/* arckey.c —— 在"候选来源文件"里暴力找 AES 密钥
 *
 * 用途：通用AES候选验证实验工具，以已知XZ magic作为判据。
 * 更正（2026-10-24）：WE410443-ST squashfs不使用此处假设的AES-ECB，
 * 已还原为固定byte变换+XZ，使用extender_rootfs.py；不再需要flash key。
 * 证据见 docs/singtel-extender-crypto-path.md。
 *
 * 做法：把候选文件里【每一个 16/32 字节窗口】都当一次密钥，
 *       用 AES-ECB 解那 16 字节密文，看解出来是不是以 xz 魔数开头。
 *
 * 编译: cc -O3 -o arckey arckey.c -lcrypto
 * 用法: ./arckey <候选来源文件> <16字节密文hex> [--hex-ascii]
 *        --hex-ascii  额外把文件里的 32 位十六进制【字符串】解成 16 字节密钥再试
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <openssl/aes.h>

static unsigned char CT[16];
static const unsigned char XZMAGIC[6] = {0xfd, 0x37, 0x7a, 0x58, 0x5a, 0x00};

static int hex2bin(const char *s, unsigned char *out, int maxn)
{
    int n = 0;
    for (; s[0] && s[1] && n < maxn; s += 2, n++) {
        int hi = isdigit((unsigned char)s[0]) ? s[0]-'0' : (tolower((unsigned char)s[0])-'a'+10);
        int lo = isdigit((unsigned char)s[1]) ? s[1]-'0' : (tolower((unsigned char)s[1])-'a'+10);
        if (hi < 0 || hi > 15 || lo < 0 || lo > 15) return -1;
        out[n] = (hi << 4) | lo;
    }
    return n;
}

/* 用 16 字节密钥 AES-128-ECB 解 CT，看开头是不是 xz 魔数 */
static int test128(const unsigned char *key, unsigned char *outp)
{
    AES_KEY a;
    if (AES_set_decrypt_key(key, 128, &a) != 0) return 0;
    unsigned char out[16];
    AES_decrypt(CT, out, &a);
    if (outp) memcpy(outp, out, 16);
    return memcmp(out, XZMAGIC, 6) == 0;
}

static int test256(const unsigned char *key, unsigned char *outp)
{
    AES_KEY a;
    if (AES_set_decrypt_key(key, 256, &a) != 0) return 0;
    unsigned char out[16];
    AES_decrypt(CT, out, &a);
    if (outp) memcpy(outp, out, 16);
    return memcmp(out, XZMAGIC, 6) == 0;
}

int main(int argc, char **argv)
{
    /* ── 自测：FIPS-197 标准测试向量 ──
     * AES-128: key=000102...0f  pt=00112233...eeff  ct=69c4e0d86a7b0430d8cdb78070b4c55a
     * AES-256: key=000102...1f  pt=00112233...eeff  ct=8ea2b7ca516745bfeafc49904b496089
     * 不先验这个，整个暴力搜索都可能建在错实现上（hwkey.c 那次连踩两个这种坑）。 */
    if (argc == 2 && !strcmp(argv[1], "--selftest")) {
        unsigned char k128[16], k256[32], pt[16], ct[16], out[16];
        hex2bin("000102030405060708090a0b0c0d0e0f", k128, 16);
        hex2bin("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", k256, 32);
        hex2bin("00112233445566778899aabbccddeeff", pt, 16);
        AES_KEY a;
        int ok = 1;
        hex2bin("69c4e0d86a7b0430d8cdb78070b4c55a", ct, 16);
        AES_set_encrypt_key(k128, 128, &a); AES_encrypt(pt, out, &a);
        printf("AES-128 加密向量: %s\n", memcmp(out, ct, 16) == 0 ? "✓ 通过" : "✗ 失败");
        if (memcmp(out, ct, 16)) ok = 0;
        AES_set_decrypt_key(k128, 128, &a); AES_decrypt(ct, out, &a);
        printf("AES-128 解密向量: %s\n", memcmp(out, pt, 16) == 0 ? "✓ 通过" : "✗ 失败");
        if (memcmp(out, pt, 16)) ok = 0;
        hex2bin("8ea2b7ca516745bfeafc49904b496089", ct, 16);
        AES_set_encrypt_key(k256, 256, &a); AES_encrypt(pt, out, &a);
        printf("AES-256 加密向量: %s\n", memcmp(out, ct, 16) == 0 ? "✓ 通过" : "✗ 失败");
        if (memcmp(out, ct, 16)) ok = 0;
        printf("\n%s\n", ok ? "★ AES 实现正确，可以放心跑暴力搜索" : "✗ 实现有问题，先别跑");
        return ok ? 0 : 1;
    }
    if (argc < 3) {
        fprintf(stderr, "用法: %s <候选来源文件> <16字节密文hex> [--hex-ascii]\n", argv[0]);
        fprintf(stderr, "      %s --selftest\n", argv[0]);
        return 2;
    }
    if (hex2bin(argv[2], CT, 16) != 16) { fprintf(stderr, "密文 hex 必须 16 字节\n"); return 2; }
    int hexmode = (argc > 3 && !strcmp(argv[3], "--hex-ascii"));

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 1; }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    unsigned char *d = malloc(n);
    if (fread(d, 1, n, f) != (size_t)n) { fprintf(stderr, "读取失败\n"); return 1; }
    fclose(f);
    printf("候选来源: %s (%ld 字节)\n判据: AES-ECB 解出来以 fd 37 7a 58 5a 00 开头\n\n", argv[1], n);

    unsigned char out[16];
    long hits = 0, tried = 0;

    /* ① 文件里每一个 16 字节窗口当 AES-128 密钥 */
    for (long i = 0; i + 16 <= n; i++) {
        tried++;
        if (test128(d + i, out)) {
            hits++;
            printf("★★★ AES-128 命中！密钥在偏移 0x%lX\n", i);
            printf("     密钥: ");
            for (int j = 0; j < 16; j++) printf("%02x", d[i+j]);
            printf("\n     解出: ");
            for (int j = 0; j < 16; j++) printf("%02x", out[j]);
            printf("\n");
        }
    }
    /* ② 每一个 32 字节窗口当 AES-256 密钥 */
    for (long i = 0; i + 32 <= n; i++) {
        tried++;
        if (test256(d + i, out)) {
            hits++;
            printf("★★★ AES-256 命中！密钥在偏移 0x%lX\n", i);
            printf("     密钥: ");
            for (int j = 0; j < 32; j++) printf("%02x", d[i+j]);
            printf("\n     解出: ");
            for (int j = 0; j < 16; j++) printf("%02x", out[j]);
            printf("\n");
        }
    }
    /* ③ 文件里 32 位十六进制【字符串】解成 16 字节密钥（密钥可能以文本形式存着）*/
    if (hexmode) {
        for (long i = 0; i + 32 <= n; i++) {
            int ok = 1;
            for (int j = 0; j < 32; j++) if (!isxdigit((unsigned char)d[i+j])) { ok = 0; break; }
            if (!ok) continue;
            unsigned char k[16];
            char tmp[33]; memcpy(tmp, d + i, 32); tmp[32] = 0;
            hex2bin(tmp, k, 16);
            tried++;
            if (test128(k, out)) {
                hits++;
                printf("★★★ 十六进制字符串密钥命中！偏移 0x%lX  ASCII=\"%.32s\"\n", i, d + i);
                printf("     解出: ");
                for (int j = 0; j < 16; j++) printf("%02x", out[j]);
                printf("\n");
            }
        }
    }
    printf("\n试了 %ld 个候选，命中 %ld 个\n", tried, hits);
    return hits ? 0 : 1;
}
