/* Host-only liblzma adapter. See docs/singtel-extender-crypto-path.md.
 * Only encoded XZ streams are transformed; no firmware code is executed. */
#define _GNU_SOURCE
#include <lzma.h>
#include <dlfcn.h>
#include <stdlib.h>

static unsigned char output_byte(unsigned char v)
{
    if (!(v & 1)) v ^= 0xda;
    if (v & 0x80) v ^= 0x55;
    switch (v & 0x28) {
        case 0:    v ^= 0x76; break;
        case 8:    v ^= 0x5e; break;
        case 0x20: v ^= 0xab; break;
        case 0x28: v ^= 0xd5; break;
    }
    return v;
}

lzma_ret lzma_stream_buffer_decode(
    uint64_t *limit, uint32_t flags, const lzma_allocator *allocator,
    const uint8_t *in, size_t *in_pos, size_t in_size,
    uint8_t *out, size_t *out_pos, size_t out_size)
{
    typedef lzma_ret (*decode_fn)(
        uint64_t *, uint32_t, const lzma_allocator *,
        const uint8_t *, size_t *, size_t, uint8_t *, size_t *, size_t);
    decode_fn real = (decode_fn)dlsym(RTLD_NEXT, "lzma_stream_buffer_decode");
    if (!real || *in_pos > in_size || *out_pos > out_size)
        return LZMA_PROG_ERROR;

    static const unsigned char magic[] = {0xaa, 0xfc, 0x96, 0x87, 0x97, 0x45};
    int encoded = in_size - *in_pos >= sizeof(magic);
    for (size_t i = 0; encoded && i < sizeof(magic); i++)
        encoded = in[*in_pos + i] == magic[i];
    if (!encoded)
        return real(limit, flags, allocator, in, in_pos, in_size,
                    out, out_pos, out_size);

    uint8_t *temporary = malloc(in_size);
    if (!temporary) return LZMA_MEM_ERROR;
    for (size_t i = 0; i < in_size; i++) {
        unsigned v = in[i] ^ 0x45;
        temporary[i] = (v >> 3) | (v << 5);
    }
    size_t begin = *out_pos;
    lzma_ret result = real(limit, flags, allocator, temporary, in_pos,
                           in_size, out, out_pos, out_size);
    if (result == LZMA_OK)
        for (size_t i = begin; i < *out_pos; i++) out[i] = output_byte(out[i]);
    free(temporary);
    return result;
}
