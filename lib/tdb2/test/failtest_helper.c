#include "failtest_helper.h"
#include "logging.h"
#include <string.h>
#include "tap-interface.h"

bool failtest_suppress = false;

/* FIXME: From ccan/str */
static inline bool strends(const char *str, const char *postfix)
{
	if (strlen(str) < strlen(postfix))
		return false;

	return !strcmp(str + strlen(str) - strlen(postfix), postfix);
}

bool failmatch(const struct failtest_call *call,
	       const char *file, int line, enum failtest_call_type type)
{
	return call->type == type
		&& call->line == line
		&& ((strcmp(call->file, file) == 0)
		    || (strends(call->file, file)
			&& (call->file[strlen(call->file) - strlen(file) - 1]
			    == '/')));
}

static bool is_nonblocking_lock(const struct failtest_call *call)
{
	return call->type == FAILTEST_FCNTL && call->u.fcntl.cmd == F_SETLK;
}

static bool is_unlock(const struct failtest_call *call)
{
	return call->type == FAILTEST_FCNTL
		&& call->u.fcntl.arg.fl.l_type == F_UNLCK;
}

bool exit_check_log(struct tlist_calls *history)
{
	const struct failtest_call *i;

	tlist_for_each(history, i, list) {
		if (!i->fail)
			continue;
		/* Failing the /dev/urandom open doesn't count: we fall back. */
		if (failmatch(i, URANDOM_OPEN))
			continue;

		/* Similarly with read fail. */
		if (failmatch(i, URANDOM_READ))
			continue;

		/* Initial allocation of tdb doesn't log. */
		if (failmatch(i, INITIAL_TDB_MALLOC))
			continue;

		/* We don't block "failures" on non-blocking locks. */
		if (is_nonblocking_lock(i))
			continue;

		if (!tap_log_messages)
			diag("We didn't log for %s:%u", i->file, i->line);
		return tap_log_messages != 0;
	}
	return true;
}

/* Some places we soldier on despite errors: only fail them once. */
enum failtest_result
block_repeat_failures(struct tlist_calls *history)
{
	const struct failtest_call *last;

	last = tlist_tail(history, list);

	if (failtest_suppress)
		return FAIL_DONT_FAIL;

	if (failmatch(last, INITIAL_TDB_MALLOC)
	    || failmatch(last, URANDOM_OPEN)
	    || failmatch(last, URANDOM_READ)) {
		return FAIL_PROBE;
	}

	/* We handle mmap failing, by falling back to read/write, so
	 * don't try all possible paths. */
	if (last->type == FAILTEST_MMAP)
		return FAIL_PROBE;

	/* Unlock or non-blocking lock is fail-once. */
	if (is_unlock(last) || is_nonblocking_lock(last))
		return FAIL_PROBE;

	return FAIL_OK;
}
