# Shared apply / stop / failover mutex. The holder keeps it on fd 9.
# A caller that already holds it exports MANGO_IKEV2_LOCK_HELD=1 so a nested
# stop (SSR fallback) does not flock the same lock and deadlock.
# Background children must close fd 9 and unset LOCK_HELD. Otherwise the
# watchdog inherits the lock for the life of the tunnel.
mango_ikev2_lifecycle_enter() {
	if [ "${MANGO_IKEV2_LOCK_HELD:-}" = 1 ]; then
		return 0
	fi
	local lock wait
	lock=${MANGO_IKEV2_LOCK:-/var/lock/mango-ikev2-lifecycle.lock}
	mkdir -p "$(dirname "$lock")" || return 1
	exec 9>"$lock"
	wait=${MANGO_IKEV2_LOCK_WAIT:-120}
	case "$wait" in
		''|*[!0-9]*) wait=120 ;;
	esac
	if ! flock -w "$wait" 9; then
		return 1
	fi
	MANGO_IKEV2_LOCK_HELD=1
	export MANGO_IKEV2_LOCK_HELD
}
