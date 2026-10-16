/* hwkey.c —— 华为 aescrypt2 配置的高速密钥破解器/验证器
 *
 * 为什么自己写：密钥派生要迭代 8192 次 SHA256，Python 一条候选 5ms 以上。
 * 这里利用一个关键优化 —— 每轮迭代的输入长度【固定】= 32 + len(key)，
 * 填充可预计算一次，之后每轮只需【1 次 SHA256 压缩】。
 *
 * 判据 = aescrypt2 密文末尾的 32 字节 HMAC-SHA256（256 位，零误判），
 * 比"看解密出来像不像明文"可靠得多。
 *
 * 编译:
 *   cc -O3 -march=native -pthread -o hwkey hwkey.c -lcrypto
 * 用法:
 *   ./hwkey <conf> verify <keystring>          # 验一把密钥
 *   ./hwkey <conf> derive <keystring>          # 打印派生密钥（交叉验证用）
 *   ./hwkey <conf> dict   <wordlist> [前缀]     # 字典（每行一条）
 *   ./hwkey <conf> mask   <模式>     [前缀]     # 掩码，如 ?l?l?l?l?l?l
 * 掩码字符集: ?l=a-z ?u=A-Z ?d=0-9 ?s=符号 ?a=可打印
 * 环境变量 THREADS 可指定线程数（默认 8）
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <pthread.h>
#include <unistd.h>
#include <time.h>
#include <sys/stat.h>
#include <openssl/sha.h>

#define MAXKEY 48
#define MAXT   32

/* ══════════ SHA256 单块压缩 ══════════ */
static const uint32_t KK[64] = {
 0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
 0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
 0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
 0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
 0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
 0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
 0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
 0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
#define ROR(x,n) (((x)>>(n))|((x)<<(32-(n))))
#define CH(x,y,z)  (((x)&(y))^(~(x)&(z)))
#define MAJ(x,y,z) (((x)&(y))^((x)&(z))^((y)&(z)))
#define EP0(x) (ROR(x,2)^ROR(x,13)^ROR(x,22))
#define EP1(x) (ROR(x,6)^ROR(x,11)^ROR(x,25))
#define SG0(x) (ROR(x,7)^ROR(x,18)^((x)>>3))
#define SG1(x) (ROR(x,17)^ROR(x,19)^((x)>>10))

static inline void one_block(uint32_t st[8], const uint32_t b[16])
{
    uint32_t w[64];
    for (int i = 0; i < 16; i++) w[i] = b[i];
    for (int i = 16; i < 64; i++) w[i] = SG1(w[i-2]) + w[i-7] + SG0(w[i-15]) + w[i-16];
    uint32_t a=st[0],bb=st[1],c=st[2],d=st[3],e=st[4],f=st[5],g=st[6],h=st[7];
    for (int i = 0; i < 64; i++) {
        uint32_t t1 = h + EP1(e) + CH(e,f,g) + KK[i] + w[i];
        uint32_t t2 = EP0(a) + MAJ(a,bb,c);
        h=g; g=f; f=e; e=d+t1; d=c; c=bb; bb=a; a=t1+t2;
    }
    st[0]+=a; st[1]+=bb; st[2]+=c; st[3]+=d; st[4]+=e; st[5]+=f; st[6]+=g; st[7]+=h;
}

/* ══════════ 密钥派生 ══════════
 * digest = IV ‖ 16 个零  →  迭代 8192 次 digest = SHA256(digest ‖ key)
 * 预计算：块里 [32..] 放 key 与填充；每轮只覆盖前 32 字节 */
typedef struct { uint32_t blk[16]; uint32_t blk2[16]; int two; } DC;

static void dc_prepare(DC *dc, const unsigned char *key, int klen)
{
    unsigned char m[128];
    int total = 32 + klen;                       /* 消息长度（不含填充） */
    memset(m, 0, sizeof m);
    memcpy(m + 32, key, klen);
    m[total] = 0x80;
    if (total + 1 <= 56) {                        /* 一个块装得下 */
        uint64_t bits = (uint64_t)total * 8;
        for (int i = 0; i < 8; i++) m[56 + i] = (bits >> (56 - i * 8)) & 0xFF;
        dc->two = 0;
    } else {                                      /* 两个块 */
        uint64_t bits = (uint64_t)total * 8;
        for (int i = 0; i < 8; i++) m[120 + i] = (bits >> (56 - i * 8)) & 0xFF;
        dc->two = 1;
    }
    for (int i = 0; i < 16; i++) {
        dc->blk[i]  = ((uint32_t)m[i*4]<<24)|((uint32_t)m[i*4+1]<<16)|
                      ((uint32_t)m[i*4+2]<<8)|(uint32_t)m[i*4+3];
        dc->blk2[i] = ((uint32_t)m[64+i*4]<<24)|((uint32_t)m[64+i*4+1]<<16)|
                      ((uint32_t)m[64+i*4+2]<<8)|(uint32_t)m[64+i*4+3];
    }
}

static void dc_key(const DC *dc, const unsigned char iv16[16], unsigned char out[32])
{
    static const uint32_t IV0[8] = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                                    0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    uint32_t mw[8], blk[16];
    for (int i = 0; i < 4; i++)                   /* digest = IV ‖ 16 个零字节 */
        mw[i] = ((uint32_t)iv16[i*4]<<24)|((uint32_t)iv16[i*4+1]<<16)|
                ((uint32_t)iv16[i*4+2]<<8)|(uint32_t)iv16[i*4+3];
    memset(mw + 4, 0, 16);

    for (int it = 0; it < 8192; it++) {
        uint32_t st[8];
        memcpy(st, IV0, sizeof st);               /* ★ 每轮都从【标准初值】开始 ——
                                                   * st 是 SHA256 的初始状态，不是消息。
                                                   * 忘了重置就会把上一轮的 digest
                                                   * 当初始状态用，结果全错。 */
        memcpy(blk, dc->blk, sizeof blk);         /* 后 32 字节 = key ‖ 填充 */
        memcpy(blk, mw, 32);                      /* 前 32 字节 = 当前 digest */
        one_block(st, blk);
        if (dc->two) one_block(st, dc->blk2);
        memcpy(mw, st, 32);                       /* 本轮结果成为下一轮的 digest */
    }
    for (int i = 0; i < 8; i++) {
        out[i*4]   = (mw[i] >> 24) & 0xFF; out[i*4+1] = (mw[i] >> 16) & 0xFF;
        out[i*4+2] = (mw[i] >> 8)  & 0xFF; out[i*4+3] = mw[i] & 0xFF;
    }
}

/* ══════════ 目标文件与判据 ══════════ */
static unsigned char *g_data; static size_t g_len;
static int g_hdr = 32, g_tag = 32;

static int hmac_ok(const unsigned char *fullkey, int flen)
{
    if (g_hdr + 16 + g_tag > (int)g_len) return 0;
    const unsigned char *iv = g_data + g_hdr;
    const unsigned char *ct = g_data + g_hdr + 16;
    size_t ctlen = g_len - g_hdr - 16 - g_tag;
    const unsigned char *want = g_data + g_len - g_tag;

    DC dc; dc_prepare(&dc, fullkey, flen);
    unsigned char k[32]; dc_key(&dc, iv, k);

    unsigned char ip[64], op[64], in[32], out[32];
    memset(ip, 0x36, 64); memset(op, 0x5c, 64);
    for (int i = 0; i < 32; i++) { ip[i] ^= k[i]; op[i] ^= k[i]; }
    SHA256_CTX c;
    SHA256_Init(&c); SHA256_Update(&c, ip, 64); SHA256_Update(&c, ct, ctlen); SHA256_Final(in, &c);
    SHA256_Init(&c); SHA256_Update(&c, op, 64); SHA256_Update(&c, in, 32); SHA256_Final(out, &c);
    return memcmp(out, want, g_tag) == 0;
}

/* ══════════ 全局状态 ══════════ */
static char g_pre[64]; static int g_prelen;
static volatile int g_found; static char g_foundk[160];
static volatile unsigned long g_cnt[MAXT];
static int g_nthreads = 8;

static int try_cand(const unsigned char *c, int n)
{
    unsigned char full[MAXKEY];
    if (g_prelen + n > MAXKEY) return 0;
    memcpy(full, g_pre, g_prelen); memcpy(full + g_prelen, c, n);
    if (hmac_ok(full, g_prelen + n)) {
        if (!g_found) { memcpy(g_foundk, full, g_prelen + n); g_foundk[g_prelen + n] = 0; g_found = 1; }
        return 1;
    }
    return 0;
}

/* ── 字典模式：整表读入内存，按字节区间分给各线程 ── */
static char *g_dict; static size_t g_dsize;

static void *dict_worker(void *arg)
{
    long id = (long)arg;
    size_t per = g_dsize / g_nthreads + 1;
    size_t s = (size_t)id * per, e = s + per; if (e > g_dsize) e = g_dsize;
    if (s >= e) return NULL;
    const char *p = g_dict + s, *end = g_dict + e;
    if (id) { const char *nl = memchr(p, '\n', end - p); if (nl) p = nl + 1; }
    while (p < end && !g_found) {
        const char *nl = memchr(p, '\n', (size_t)(end - p));
        size_t l = nl ? (size_t)(nl - p) : (size_t)(end - p);
        if (l && p[l-1] == '\r') l--;
        if (l > 0 && l <= MAXKEY - g_prelen) try_cand((const unsigned char *)p, (int)l);
        g_cnt[id]++;
        if (!nl) break;
        p = nl + 1;
    }
    return NULL;
}

/* ── 掩码模式：索引空间按 id 步进 ── */
static char g_cs[16][128]; static int g_csn[16]; static int g_mlen;
static unsigned long long g_mtotal;

static void mask_charsets(const char *mask)
{
    g_mlen = 0;
    for (const char *p = mask; *p; ) {
        int n = 1;
        if (*p == '?' && p[1]) {
            p++;
            switch (*p) {
                case 'l': for (char c='a'; c<='z'; c++) g_cs[g_mlen][n++-1] = c; n = 27; break;
                case 'u': for (char c='A'; c<='Z'; c++) g_cs[g_mlen][n++-1] = c; n = 27; break;
                case 'd': for (char c='0'; c<='9'; c++) g_cs[g_mlen][n++-1] = c; n = 11; break;
                case 's': { const char *s="!@#$%^&*()-_=+[]{};:,.<>/?"; n = 1;
                            while (*s) g_cs[g_mlen][n++-1] = *s++; break; }
                case 'a': for (int c=32; c<127; c++) g_cs[g_mlen][n++-1] = (char)c; n = 96; break;
                default:  g_cs[g_mlen][0] = *p; n = 2;
            }
        } else {
            g_cs[g_mlen][0] = *p; n = 2;
        }
        g_csn[g_mlen] = n - 1;
        g_mlen++;
        p++;
        if (g_mlen >= 16) break;
    }
    g_mtotal = 1;
    for (int i = 0; i < g_mlen; i++) g_mtotal *= (unsigned long long)g_csn[i];
}

static void *mask_worker(void *arg)
{
    long id = (long)arg;
    unsigned char buf[16];
    for (unsigned long long idx = (unsigned long long)id; idx < g_mtotal && !g_found; idx += (unsigned long long)g_nthreads) {
        unsigned long long v = idx;
        for (int i = g_mlen - 1; i >= 0; i--) { buf[i] = g_cs[i][v % g_csn[i]]; v /= g_csn[i]; }
        try_cand(buf, g_mlen);
        g_cnt[id]++;
    }
    return NULL;
}

/* ── 主 ── */
static unsigned char *readfile(const char *p, size_t *n)
{
    FILE *f = fopen(p, "rb");
    if (!f) { perror(p); exit(1); }
    struct stat st; fstat(fileno(f), &st);
    unsigned char *b = malloc((size_t)st.st_size + 1);
    if (fread(b, 1, (size_t)st.st_size, f) != (size_t)st.st_size) { fprintf(stderr, "读取 %s 失败\n", p); exit(1); }
    fclose(f); *n = (size_t)st.st_size; return b;
}

static void usage(const char *a)
{
    fprintf(stderr,
      "用法:\n"
      "  %s <conf> verify <keystring>\n"
      "  %s <conf> derive <keystring>\n"
      "  %s <conf> dict   <wordlist> [前缀]\n"
      "  %s <conf> mask   <模式>     [前缀]     (?l=a-z ?u=A-Z ?d=0-9 ?s=符号 ?a=可打印)\n"
      "环境变量 THREADS 指定线程数（默认 8）\n", a,a,a,a);
}

int main(int argc, char **argv)
{
    if (argc < 4) { usage(argv[0]); return 2; }
    size_t n; g_data = readfile(argv[1], &n); g_len = n;
    { const char *t = getenv("THREADS"); if (t) g_nthreads = atoi(t);
      if (g_nthreads < 1) g_nthreads = 1; if (g_nthreads > MAXT) g_nthreads = MAXT; }
    const char *mode = argv[2];

    if (!strcmp(mode, "derive")) {
        DC dc; dc_prepare(&dc, (const unsigned char *)argv[3], strlen(argv[3]));
        unsigned char k[32]; dc_key(&dc, g_data + g_hdr, k);
        for (int i = 0; i < 32; i++) printf("%02x", k[i]);
        printf("\n");
        return 0;
    }
    if (!strcmp(mode, "verify")) {
        DC dc; dc_prepare(&dc, (const unsigned char *)argv[3], strlen(argv[3]));
        int ok = hmac_ok((const unsigned char *)argv[3], strlen(argv[3]));
        (void)dc;
        printf("%s : %s\n", argv[3], ok ? "★ HMAC 通过 —— 密钥正确" : "✗ 不通过");
        return ok ? 0 : 1;
    }
    if (argc >= 5) g_prelen = snprintf(g_pre, sizeof g_pre, "%s", argv[4]);

    struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
    pthread_t th[MAXT];

    if (!strcmp(mode, "dict")) {
        g_dict = (char *)readfile(argv[3], &g_dsize);
        fprintf(stderr, "字典 %zu 字节，%d 线程，前缀 %s\n", g_dsize, g_nthreads,
                g_prelen ? g_pre : "(无)");
        for (long i = 0; i < g_nthreads; i++) pthread_create(&th[i], NULL, dict_worker, (void *)i);
        for (int i = 0; i < g_nthreads; i++) pthread_join(th[i], NULL);
    } else if (!strcmp(mode, "mask")) {
        mask_charsets(argv[3]);
        fprintf(stderr, "掩码 %s → %llu 个组合，%d 线程，前缀 %s\n",
                argv[3], g_mtotal, g_nthreads, g_prelen ? g_pre : "(无)");
        for (long i = 0; i < g_nthreads; i++) pthread_create(&th[i], NULL, mask_worker, (void *)i);
        for (int i = 0; i < g_nthreads; i++) pthread_join(th[i], NULL);
    } else { usage(argv[0]); return 2; }

    clock_gettime(CLOCK_MONOTONIC, &t1);
    double sec = (t1.tv_sec - t0.tv_sec) + (t1.tv_nsec - t0.tv_nsec) / 1e9;
    unsigned long tot = 0;
    for (int i = 0; i < g_nthreads; i++) tot += g_cnt[i];
    fprintf(stderr, "\n试了 %lu 条，用时 %.1fs，速度 %.0f/s\n", tot, sec, tot / (sec > 0 ? sec : 1));
    if (g_found) printf("\n★★★ 找到密钥: %s\n", g_foundk);
    else printf("\n未找到\n");
    return g_found ? 0 : 1;
}
