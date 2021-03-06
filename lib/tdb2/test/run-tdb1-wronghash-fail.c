#include "tdb2-source.h"
#include "tap-interface.h"
#include <stdlib.h>
#include <err.h>

static void log_fn(struct tdb_context *tdb, enum tdb_log_level level,
		   enum TDB_ERROR ecode, const char *message, void *priv)
{
	unsigned int *count = priv;
	if (strstr(message, "hash"))
		(*count)++;
}

static uint64_t jenkins_hashfn(const void *key, size_t len, uint64_t seed,
			       void *unused)
{
	return hashlittle(key, len);
}

/* the tdb1_old_hash function is "magic" as it automatically makes us test the
 * tdb1_incompatible_hash as well, so use this wrapper. */
static uint64_t old_hash(const void *key, size_t len, uint64_t seed,
			 void *unused)
{
	return tdb1_old_hash(key, len, seed, unused);
}

int main(int argc, char *argv[])
{
	struct tdb_context *tdb;
	unsigned int log_count;
	TDB_DATA d;
	union tdb_attribute log_attr, jhash_attr, ohash_attr,
		incompat_hash_attr;

	log_attr.base.attr = TDB_ATTRIBUTE_LOG;
	log_attr.base.next = NULL;
	log_attr.log.fn = log_fn;
	log_attr.log.data = &log_count;

	jhash_attr.base.attr = TDB_ATTRIBUTE_HASH;
	jhash_attr.base.next = &log_attr;
	jhash_attr.hash.fn = jenkins_hashfn;

	ohash_attr.base.attr = TDB_ATTRIBUTE_HASH;
	ohash_attr.base.next = &log_attr;
	ohash_attr.hash.fn = old_hash;

	incompat_hash_attr.base.attr = TDB_ATTRIBUTE_HASH;
	incompat_hash_attr.base.next = &log_attr;
	incompat_hash_attr.hash.fn = tdb1_incompatible_hash;

	plan_tests(28);

	/* Create with default hash. */
	log_count = 0;
	tdb = tdb_open("run-wronghash-fail.tdb1", TDB_VERSION1,
		       O_CREAT|O_RDWR|O_TRUNC, 0600, &log_attr);
	ok1(tdb);
	ok1(log_count == 0);
	d = tdb_mkdata("Hello", strlen("Hello"));
	ok1(tdb_store(tdb, d, d, TDB_INSERT) == TDB_SUCCESS);
	tdb_close(tdb);

	/* Fail to open with different hash. */
	tdb = tdb_open("run-wronghash-fail.tdb1", TDB_VERSION1, O_RDWR, 0,
		       &jhash_attr);
	ok1(!tdb);
	ok1(log_count == 1);

	/* Create with different hash. */
	log_count = 0;
	tdb = tdb_open("run-wronghash-fail.tdb1", TDB_VERSION1,
		       O_CREAT|O_RDWR|O_TRUNC, 0600, &jhash_attr);
	ok1(tdb);
	ok1(log_count == 0);
	tdb_close(tdb);

	/* Endian should be no problem. */
	log_count = 0;
	tdb = tdb_open("test/jenkins-le-hash.tdb1", TDB_VERSION1, O_RDWR, 0,
		       &ohash_attr);
	ok1(!tdb);
	ok1(log_count == 1);

	log_count = 0;
	tdb = tdb_open("test/jenkins-be-hash.tdb1", TDB_VERSION1, O_RDWR, 0,
		       &ohash_attr);
	ok1(!tdb);
	ok1(log_count == 1);

	log_count = 0;
	/* Fail to open with old default hash. */
	tdb = tdb_open("run-wronghash-fail.tdb1", TDB_VERSION1, O_RDWR, 0,
		       &ohash_attr);
	ok1(!tdb);
	ok1(log_count == 1);

	log_count = 0;
	tdb = tdb_open("test/jenkins-le-hash.tdb1", TDB_VERSION1, O_RDONLY,
		       0, &incompat_hash_attr);
	ok1(tdb);
	ok1(log_count == 0);
	ok1(tdb_check(tdb, NULL, NULL) == TDB_SUCCESS);
	tdb_close(tdb);

	log_count = 0;
	tdb = tdb_open("test/jenkins-be-hash.tdb1", TDB_VERSION1, O_RDONLY,
		       0, &incompat_hash_attr);
	ok1(tdb);
	ok1(log_count == 0);
	ok1(tdb_check(tdb, NULL, NULL) == TDB_SUCCESS);
	tdb_close(tdb);

	/* It should open with jenkins hash if we don't specify. */
	log_count = 0;
	tdb = tdb_open("test/jenkins-le-hash.tdb1", TDB_VERSION1, O_RDWR, 0,
		       &log_attr);
	ok1(tdb);
	ok1(log_count == 0);
	ok1(tdb_check(tdb, NULL, NULL) == TDB_SUCCESS);
	tdb_close(tdb);

	log_count = 0;
	tdb = tdb_open("test/jenkins-be-hash.tdb1", TDB_VERSION1, O_RDWR, 0,
		       &log_attr);
	ok1(tdb);
	ok1(log_count == 0);
	ok1(tdb_check(tdb, NULL, NULL) == TDB_SUCCESS);
	tdb_close(tdb);

	log_count = 0;
	tdb = tdb_open("run-wronghash-fail.tdb1", TDB_VERSION1, O_RDONLY,
		       0, &log_attr);
	ok1(tdb);
	ok1(log_count == 0);
	ok1(tdb_check(tdb, NULL, NULL) == TDB_SUCCESS);
	tdb_close(tdb);


	return exit_status();
}
