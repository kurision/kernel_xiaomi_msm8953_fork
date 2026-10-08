// SPDX-License-Identifier: GPL-2.0-only
/*
 * EROFS zstd decompression, adapted to the 4.19-era
 * decompress(rq, out) interface from the 6.12 streaming version.
 * One-shot decode per pcluster; per-call workspace keeps this
 * lock-free with no lifetime management ( allocator churn is
 * noise next to flash I/O on this platform).
 */
#include "compress.h"
#include <linux/zstd.h>
#include <linux/vmalloc.h>

int z_erofs_load_zstd_config(struct super_block *sb,
			     struct erofs_super_block *dsb,
			     struct z_erofs_zstd_cfgs *zstd, int size)
{
	unsigned int dict_size;

	if (!zstd || size < sizeof(struct z_erofs_zstd_cfgs) || zstd->format) {
		erofs_err(sb, "invalid zstd cfgs, size=%d", size);
		return -EINVAL;
	}

	/* windowlog is stored minus ZSTD_WINDOWLOG_ABSOLUTEMIN(10) */
	if (zstd->windowlog > ilog2(Z_EROFS_ZSTD_MAX_DICT_SIZE) - 10) {
		erofs_err(sb, "unsupported zstd windowlog %u", zstd->windowlog);
		return -EINVAL;
	}
	dict_size = 1U << (zstd->windowlog + 10);
	if (dict_size > Z_EROFS_ZSTD_MAX_DICT_SIZE) {
		erofs_err(sb, "too large zstd dict size %u", dict_size);
		return -EINVAL;
	}

	/* one-shot decode needs no superblock state; validated above */
	(void)dsb;
	return 0;
}

int z_erofs_zstd_prepare_destpages(struct z_erofs_decompress_req *rq,
				   struct list_head *pagepool)
{
	const unsigned int nr =
		PAGE_ALIGN(rq->pageofs_out + rq->outputsize) >> PAGE_SHIFT;
	void *kaddr = NULL;
	unsigned int i;

	for (i = 0; i < nr; ++i) {
		struct page *const page = rq->out[i];

		if (page) {
			if (!PageHighMem(page)) {
				if (!i) {
					kaddr = page_address(page);
					continue;
				}
				if (kaddr &&
				    kaddr + PAGE_SIZE == page_address(page)) {
					kaddr += PAGE_SIZE;
					continue;
				}
			}
			kaddr = NULL;
			continue;
		}
		kaddr = NULL;
		rq->out[i] = erofs_allocpage(pagepool,
					     GFP_KERNEL | __GFP_NOFAIL);
		set_page_private(rq->out[i], Z_EROFS_SHORTLIVED_PAGE);
	}
	return kaddr ? 1 : 0;
}

int z_erofs_zstd_decompress(struct z_erofs_decompress_req *rq, u8 *out)
{
	const unsigned int nrpages_in =
		DIV_ROUND_UP(rq->inputsize, PAGE_SIZE);
	const size_t wkspsz = zstd_dctx_workspace_bound();
	void *wksp, *src = NULL;
	zstd_dctx *dctx;
	size_t ret;
	unsigned int i, off = 0;

	if (!rq->inputsize || !rq->outputsize)
		return -EIO;

	/* gather the (page-aligned, offset-0) compressed input contiguously */
	src = kvmalloc(rq->inputsize, GFP_KERNEL);
	if (!src)
		return -ENOMEM;
	for (i = 0; i < nrpages_in; ++i) {
		const unsigned int len =
			min_t(unsigned int, PAGE_SIZE, rq->inputsize - off);
		void *kaddr = kmap_atomic(rq->in[i]);

		memcpy(src + off, kaddr, len);
		kunmap_atomic(kaddr);
		off += len;
	}

	wksp = kvmalloc(wkspsz, GFP_KERNEL);
	if (!wksp) {
		kvfree(src);
		return -ENOMEM;
	}
	dctx = zstd_init_dctx(wksp, wkspsz);
	if (!dctx) {
		kvfree(wksp);
		kvfree(src);
		return -EIO;
	}

	ret = zstd_decompress_dctx(dctx, out, rq->outputsize,
				   src, rq->inputsize);
	kvfree(wksp);
	kvfree(src);

	if (zstd_is_error(ret)) {
		erofs_err(rq->sb, "failed to decompress zstd in[%u] out[%u]",
			  rq->inputsize, rq->outputsize);
		return -EIO;
	}
	if (ret != rq->outputsize) {
		erofs_err(rq->sb, "zstd short output %zu != %u",
			  ret, rq->outputsize);
		return -EIO;
	}
	return 0;
}

