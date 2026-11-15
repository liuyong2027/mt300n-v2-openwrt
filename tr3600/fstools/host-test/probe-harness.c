#include <errno.h>
#include <stdio.h>
#include <stdlib.h>

#include "libblkid-tiny.h"

int main(int argc, char **argv)
{
	struct blkid_struct_probe *pr;
	int rc;

	if (argc != 3) {
		fprintf(stderr, "usage: %s IMAGE ERRNO\n", argv[0]);
		return 2;
	}
	pr = blkidtiny_new_probe();
	if (!pr)
		return 2;
	errno = atoi(argv[2]);
	rc = probe_block(argv[1], pr);
	printf("rc=%d err=%d id=%s uuid=%s label=%s ver=%s\n",
		rc, pr->err,
		pr->id ? pr->id->name : "",
		pr->uuid, pr->label, pr->version);
	blkidtiny_free_probe(pr);
	return 0;
}
