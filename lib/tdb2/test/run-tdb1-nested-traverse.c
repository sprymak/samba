#include "tdb1-lock-tracking.h"
#define fcntl fcntl_with_lockcheck1
#include "tdb2-source.h"
#include "tap-interface.h"
#undef fcntl
#include <stdlib.h>
#include <stdbool.h>
#include <err.h>
#include "tdb1-external-agent.h"
#include "logging.h"

static struct agent *agent;

static bool correct_key(TDB_DATA key)
{
	return key.dsize == strlen("hi")
		&& memcmp(key.dptr, "hi", key.dsize) == 0;
}

static bool correct_data(TDB_DATA data)
{
	return data.dsize == strlen("world")
		&& memcmp(data.dptr, "world", data.dsize) == 0;
}

static int traverse2(struct tdb_context *tdb, TDB_DATA key, TDB_DATA data,
		     void *p)
{
	ok1(correct_key(key));
	ok1(correct_data(data));
	return 0;
}

static int traverse1(struct tdb_context *tdb, TDB_DATA key, TDB_DATA data,
		     void *p)
{
	ok1(correct_key(key));
	ok1(correct_data(data));
	ok1(external_agent_operation1(agent, TRANSACTION_START, tdb->name)
	    == WOULD_HAVE_BLOCKED);
	tdb_traverse(tdb, traverse2, NULL);

	/* That should *not* release the transaction lock! */
	ok1(external_agent_operation1(agent, TRANSACTION_START, tdb->name)
	    == WOULD_HAVE_BLOCKED);
	return 0;
}

int main(int argc, char *argv[])
{
	struct tdb_context *tdb;
	TDB_DATA key, data;
	union tdb_attribute hsize;

	hsize.base.attr = TDB_ATTRIBUTE_TDB1_HASHSIZE;
	hsize.base.next = &tap_log_attr;
	hsize.tdb1_hashsize.hsize = 1024;

	plan_tests(17);
	agent = prepare_external_agent1();
	if (!agent)
		err(1, "preparing agent");

	tdb = tdb_open("run-nested-traverse.tdb1", TDB_VERSION1,
		       O_CREAT|O_TRUNC|O_RDWR, 0600, &hsize);
	ok1(tdb);

	ok1(external_agent_operation1(agent, OPEN, tdb->name) == SUCCESS);
	ok1(external_agent_operation1(agent, TRANSACTION_START, tdb->name)
	    == SUCCESS);
	ok1(external_agent_operation1(agent, TRANSACTION_COMMIT, tdb->name)
	    == SUCCESS);

	key = tdb_mkdata("hi", strlen("hi"));
	data = tdb_mkdata("world", strlen("world"));

	ok1(tdb_store(tdb, key, data, TDB_INSERT) == TDB_SUCCESS);
	tdb_traverse(tdb, traverse1, NULL);
	tdb_add_flag(tdb, TDB_RDONLY);
	tdb_traverse(tdb, traverse1, NULL);
	tdb_remove_flag(tdb, TDB_RDONLY);
	tdb_close(tdb);

	return exit_status();
}
