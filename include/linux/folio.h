/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Folio compatibility layer for this 4.19 tree.
 *
 * The MGLRU port is taken from Android Common android16-6.12, where a folio is
 * a struct folio. This tree has no folio type and no compound folios
 * (CONFIG_TRANSPARENT_HUGEPAGE is not set), so a folio is exactly one struct
 * page and every folio_* helper below is a rename of the page helper that 4.19
 * already has. Keep this file a pure rename layer: anything that needs real
 * folio semantics (compound folios, folio refcounting, folio allocator) has no
 * place here and must be handled in the MGLRU code instead.
 */
#ifndef _LINUX_FOLIO_H
#define _LINUX_FOLIO_H

#include <linux/mm.h>
#include <linux/pagemap.h>

/* geometry and identity */
static inline int folio_nr_pages(struct page *page)
{
	return hpage_nr_pages(page);
}

static inline enum zone_type folio_zonenum(struct page *page)
{
	return page_zonenum(page);
}

static inline int folio_nid(struct page *page)
{
	return page_to_nid(page);
}

static inline pg_data_t *folio_pgdat(struct page *page)
{
	return page_pgdat(page);
}

static inline struct address_space *folio_mapping(struct page *page)
{
	return page_mapping(page);
}

static inline struct mem_cgroup *folio_memcg(struct page *page)
{
	return page_memcg(page);
}

static inline struct mem_cgroup *folio_memcg_rcu(struct page *page)
{
	return page_memcg_rcu(page);
}

static inline bool folio_mapped(struct page *page)
{
	return page_mapped(page);
}

static inline struct list_head *folio_lru_list(struct page *page)
{
	return &page->lru;
}

static inline struct page *pfn_folio(unsigned long pfn)
{
	return compound_head(pfn_to_page(pfn));
}

static inline struct page *lru_to_folio(struct list_head *head)
{
	return lru_to_page(head);
}

/* refcounting */
static inline bool folio_try_get(struct page *page)
{
	return !!get_page_unless_zero(page);
}

static inline void folio_put(struct page *page)
{
	put_page(page);
}

/* LRU */
static inline void folio_activate(struct page *page)
{
	activate_page(page);
}

static inline void folio_add_lru(struct page *page)
{
	lru_cache_add(page);
}

static inline void folio_putback_lru(struct page *page)
{
	lru_cache_add(page);
	put_page(page);
}

static inline int folio_is_file_lru(struct page *page)
{
	return !PageSwapBacked(page);
}

static inline bool folio_evictable(struct page *page)
{
	bool ret;

	/* Prevent address_space of inode and swap cache from being freed */
	rcu_read_lock();
	ret = !mapping_unevictable(page_mapping(page)) &&
		!PageMlocked(page);
	rcu_read_unlock();
	return ret;
}

/* writeback and dirtiness */
static inline void folio_mark_dirty(struct page *page)
{
	set_page_dirty(page);
}

static inline void folio_end_writeback(struct page *page)
{
	end_page_writeback(page);
}

/* page flag renames */
#define folio_test_swapbacked(page)	PageSwapBacked(page)
#define folio_test_swapcache(page)	PageSwapCache(page)
#define folio_test_anon(page)		PageAnon(page)
#define folio_test_dirty(page)		PageDirty(page)
#define folio_test_writeback(page)	PageWriteback(page)
#define folio_test_referenced(page)	PageReferenced(page)
#define folio_test_workingset(page)	PageWorkingset(page)
#define folio_test_lru(page)		PageLRU(page)
#define folio_test_active(page)		PageActive(page)
#define folio_test_unevictable(page)	PageUnevictable(page)
#define folio_test_reclaim(page)	PageReclaim(page)
#define folio_test_mlocked(page)	PageMlocked(page)
#define folio_test_large(page)		PageCompound(page)

#define folio_set_active(page)		SetPageActive(page)
#define folio_set_workingset(page)	SetPageWorkingset(page)
#define folio_set_unevictable(page)	SetPageUnevictable(page)

#define folio_clear_reclaim(page)	ClearPageReclaim(page)
#define folio_test_clear_lru(page)	TestClearPageLRU(page)

#endif /* _LINUX_FOLIO_H */