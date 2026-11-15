/* Minimal list helpers so the fstools host test can compile without libubox. */
#ifndef _LIBUBOX_LIST_H
#define _LIBUBOX_LIST_H

#include <stddef.h>

struct list_head {
	struct list_head *next, *prev;
};

#define INIT_LIST_HEAD(ptr) do { \
	(ptr)->next = (ptr); (ptr)->prev = (ptr); \
} while (0)

static inline void __list_add(struct list_head *newer,
		struct list_head *prev, struct list_head *next)
{
	next->prev = newer;
	newer->next = next;
	newer->prev = prev;
	prev->next = newer;
}

static inline void list_add_tail(struct list_head *newer, struct list_head *head)
{
	__list_add(newer, head->prev, head);
}

static inline int list_empty(const struct list_head *head)
{
	return head->next == head;
}

static inline void list_del(struct list_head *entry)
{
	entry->next->prev = entry->prev;
	entry->prev->next = entry->next;
	entry->next = entry;
	entry->prev = entry;
}

#ifndef container_of
#define container_of(ptr, type, member) ({ \
	const typeof(((type *)0)->member) *__mptr = (ptr); \
	(type *)((char *)__mptr - offsetof(type, member)); })
#endif

#define list_entry(ptr, type, member) container_of(ptr, type, member)
#define list_first_entry(ptr, type, member) list_entry((ptr)->next, type, member)

#endif
