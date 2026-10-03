/*
 * Macros for manipulating and testing flags related to a
 * pageblock_nr_pages number of pages.
 *
 * This program is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation version 2 of the License
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program; if not, write to the Free Software
 * Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA 02111-1307, USA.
 *
 * Copyright (C) IBM Corporation, 2006
 *
 * Original author, Mel Gorman
 * Major cleanups and reduction of bit operations, Andy Whitcroft
 */
#ifndef PAGEBLOCK_FLAGS_H
#define PAGEBLOCK_FLAGS_H

#include <linux/types.h>

/* Bit indices that affect a whole block of pages */
enum pageblock_bits {
	PB_migrate,
	PB_migrate_end = PB_migrate + 3 - 1,
			/* 3 bits required for migrate types */
	PB_migrate_skip,/* If set the block is skipped by compaction */

	/*
	 * Assume the bits will always align on a word. If this assumption
	 * changes then get/set pageblock needs updating.
	 */
	NR_PAGEBLOCK_BITS
};

#ifdef CONFIG_HUGETLB_PAGE

#ifdef CONFIG_HUGETLB_PAGE_SIZE_VARIABLE

/* Huge page sizes are variable */
extern unsigned int pageblock_order;

#else /* CONFIG_HUGETLB_PAGE_SIZE_VARIABLE */

/* Huge pages are a constant size */
#define pageblock_order		HUGETLB_PAGE_ORDER

#endif /* CONFIG_HUGETLB_PAGE_SIZE_VARIABLE */

#else /* CONFIG_HUGETLB_PAGE */

/*
 * The page allocator frees pages in pageblock-sized groups, and it does so
 * with the zone lock held. At (MAX_ORDER-1) on a 4K-page arm64 build that is
 * 1024 pages, i.e. a 4MiB pageblock, so a single pass through
 * move_freepages_block() can hold the zone lock for tens of milliseconds and
 * stall every other task that needs to allocate. Shrinking the pageblock to
 * PAGE_ALLOC_COSTLY_ORDER (order 3) cuts that critical section by 128x while
 * still letting any non-costly allocation be satisfied from a single
 * pageblock. Under sustained reclaim this is the difference between a
 * visible stall and none.
 */
#define pageblock_order		PAGE_ALLOC_COSTLY_ORDER

#endif /* CONFIG_HUGETLB_PAGE */

#define pageblock_nr_pages	(1UL << pageblock_order)

/* Forward declaration */
struct page;

unsigned long get_pfnblock_flags_mask(struct page *page,
				unsigned long pfn,
				unsigned long end_bitidx,
				unsigned long mask);

void set_pfnblock_flags_mask(struct page *page,
				unsigned long flags,
				unsigned long pfn,
				unsigned long end_bitidx,
				unsigned long mask);

/* Declarations for getting and setting flags. See mm/page_alloc.c */
#define get_pageblock_flags_group(page, start_bitidx, end_bitidx) \
	get_pfnblock_flags_mask(page, page_to_pfn(page),		\
			end_bitidx,					\
			(1 << (end_bitidx - start_bitidx + 1)) - 1)
#define set_pageblock_flags_group(page, flags, start_bitidx, end_bitidx) \
	set_pfnblock_flags_mask(page, flags, page_to_pfn(page),		\
			end_bitidx,					\
			(1 << (end_bitidx - start_bitidx + 1)) - 1)

#ifdef CONFIG_COMPACTION
#define get_pageblock_skip(page) \
			get_pageblock_flags_group(page, PB_migrate_skip,     \
							PB_migrate_skip)
#define clear_pageblock_skip(page) \
			set_pageblock_flags_group(page, 0, PB_migrate_skip,  \
							PB_migrate_skip)
#define set_pageblock_skip(page) \
			set_pageblock_flags_group(page, 1, PB_migrate_skip,  \
							PB_migrate_skip)
#else
static inline bool get_pageblock_skip(struct page *page)
{
	return false;
}
static inline void clear_pageblock_skip(struct page *page)
{
}
static inline void set_pageblock_skip(struct page *page)
{
}
#endif /* CONFIG_COMPACTION */

#endif	/* PAGEBLOCK_FLAGS_H */
