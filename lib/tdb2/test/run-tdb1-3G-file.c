#include "tdb2-source.h"
#include "tap-interface.h"
#include <stdlib.h>
#include <err.h>
#include "logging.h"

static int tdb1_expand_file_sparse(struct tdb_context *tdb,
				  tdb1_off_t size,
				  tdb1_off_t addition)
{
	if ((tdb->flags & TDB_RDONLY) || tdb->tdb1.traverse_read) {
		tdb->last_error = TDB_ERR_RDONLY;
		return -1;
	}

	if (ftruncate(tdb->file->fd, size+addition) == -1) {
		char b = 0;
		ssize_t written = pwrite(tdb->file->fd,  &b, 1, (size+addition) - 1);
		if (written == 0) {
			/* try once more, potentially revealing errno */
			written = pwrite(tdb->file->fd,  &b, 1, (size+addition) - 1);
		}
		if (written == 0) {
			/* again - give up, guessing errno */
			errno = ENOSPC;
		}
		if (written != 1) {
			tdb->last_error = tdb_logerr(tdb, TDB_ERR_IO, TDB_LOG_ERROR,
						"expand_file to %d failed (%s)",
						size+addition,
						strerror(errno));
			return -1;
		}
	}

	return 0;
}

static const struct tdb1_methods large_io_methods = {
	tdb1_read,
	tdb1_write,
	tdb1_next_hash_chain,
	tdb1_oob,
	tdb1_expand_file_sparse
};

static int test_traverse(struct tdb_context *tdb, TDB_DATA key, TDB_DATA data,
			 void *_data)
{
	TDB_DATA *expect = _data;
	ok1(key.dsize == strlen("hi"));
	ok1(memcmp(key.dptr, "hi", strlen("hi")) == 0);
	ok1(data.dsize == expect->dsize);
	ok1(memcmp(data.dptr, expect->dptr, data.dsize) == 0);
	return 0;
}

int main(int argc, char *argv[])
{
	struct tdb_context *tdb;
	TDB_DATA key, orig_data, data;
	uint32_t hash;
	tdb1_off_t rec_ptr;
	struct tdb1_record rec;
	union tdb_attribute hsize;
	int ret;

	hsize.base.attr = TDB_ATTRIBUTE_TDB1_HASHSIZE;
	hsize.base.next = &tap_log_attr;
	hsize.tdb1_hashsize.hsize = 1024;

	plan_tests(26);
	tdb = tdb_open("run-36-file.tdb1", TDB_VERSION1,
		       O_CREAT|O_TRUNC|O_RDWR, 0600, &hsize);

	ok1(tdb);
	tdb->tdb1.io = &large_io_methods;

	key = tdb_mkdata("hi", strlen("hi"));
	orig_data = tdb_mkdata("world", strlen("world"));

	/* Enlarge the file (internally multiplies by 2). */
	ret = tdb1_expand(tdb, 1500000000);

#ifdef HAVE_INCOHERENT_MMAP
	/* This can fail due to mmap failure on 32 bit systems. */
	if (ret == -1) {
		/* These should now fail. */
		ok1(tdb_store(tdb, key, orig_data, TDB_INSERT) == TDB_ERR_IO);
		ok1(tdb_fetch(tdb, key, &data) == TDB_ERR_IO);
		ok1(tdb_traverse(tdb, test_traverse, &orig_data) == TDB_ERR_IO);
		ok1(tdb_delete(tdb, key) == TDB_ERR_IO);
		ok1(tdb_traverse(tdb, test_traverse, NULL) == TDB_ERR_IO);
		/* Skip the rest... */
		for (ret = 0; ret < 26 - 6; ret++)
			ok1(1);
		tdb_close(tdb);
		return exit_status();
	}
#endif
	ok1(ret == 0);

	/* Put an entry in, and check it. */
	ok1(tdb_store(tdb, key, orig_data, TDB_INSERT) == TDB_SUCCESS);

	ok1(tdb_fetch(tdb, key, &data) == TDB_SUCCESS);
	ok1(data.dsize == strlen("world"));
	ok1(memcmp(data.dptr, "world", strlen("world")) == 0);
	free(data.dptr);

	/* That currently fills at the end, make sure that's true. */
	hash = tdb_hash(tdb, key.dptr, key.dsize);
	rec_ptr = tdb1_find_lock_hash(tdb, key, hash, F_RDLCK, &rec);
	ok1(rec_ptr);
	ok1(rec_ptr > 2U*1024*1024*1024);
	tdb1_unlock(tdb, TDB1_BUCKET(rec.full_hash), F_RDLCK);

	/* Traverse must work. */
	ok1(tdb_traverse(tdb, test_traverse, &orig_data) == 1);

	/* Delete should work. */
	ok1(tdb_delete(tdb, key) == TDB_SUCCESS);

	ok1(tdb_traverse(tdb, test_traverse, NULL) == 0);

	/* Transactions should work. */
	ok1(tdb_transaction_start(tdb) == TDB_SUCCESS);
	ok1(tdb_store(tdb, key, orig_data, TDB_INSERT) == TDB_SUCCESS);

	ok1(tdb_fetch(tdb, key, &data) == TDB_SUCCESS);
	ok1(data.dsize == strlen("world"));
	ok1(memcmp(data.dptr, "world", strlen("world")) == 0);
	free(data.dptr);
	ok1(tdb_transaction_commit(tdb) == TDB_SUCCESS);

	ok1(tdb_traverse(tdb, test_traverse, &orig_data) == 1);
	tdb_close(tdb);

	return exit_status();
}
