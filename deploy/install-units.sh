#!/bin/sh
#
# Install the units and helper scripts a deploy cannot otherwise reach.
#
# The problem this closes: everything under `deploy/` is installed as a *copy*, so a commit
# that changes a unit file lands in /opt/sms-gate and stops there. The deploy reports success,
# the service restarts, and the change is simply absent. It happened silently to `RestartSec`
# in 0.12.0, to a uvicorn bind, to two nginx blocks, and — for months — to the tunnel
# watchdog's ability to deliver an alert over the backup uplink.
#
# Three properties, each deliberate:
#
# 1. This script is root-owned and lives outside the deployed tree. A push can change what is
#    installed, but not *where* — because a manifest a push could edit is not a manifest.
#    Updating this file is a manual act; that is the boundary, not an oversight.
#
# 2. Only environment-neutral files appear below. This repository publishes the shape and not
#    the address, so the tunnel watchdog and the nginx blocks carry example values here and
#    real ones on the machine. Installing those would point the watchdog at an address nothing
#    answers on and rewrite a server block to a hostname nobody calls. Machine-specific values
#    belong in /etc/wg-tunnel-check.env, /etc/default/wwan-backup and the systemd drop-in — not
#    in files a deploy overwrites. The nginx blocks stay out permanently: `listen` and
#    `server_name` do not parameterise.
#
# 3. It says which commit it installed from. Installing by hand from /opt/sms-gate reports
#    success while copying whatever that tree happens to hold, which — if the deploy has not
#    run — is the previous version. Observed on 2026-08-01: an install ran, said nothing, and
#    left the old script in place.
#
# Note on privilege: reached by NOPASSWD sudo from the post-receive hook, so whoever can push
# can cause root to write a unit file — and a unit file names a command. Push access is
# therefore equivalent to root on this host. That cannot be narrowed away while deploys
# install units at all; it is accepted knowingly rather than by omission.

set -u

SRC=/opt/sms-gate/deploy
changed=0
units_changed=0
failed=0
timers=""

[ -d "$SRC" ] || { echo "no deployed tree at $SRC" >&2; exit 1; }

install_one() {
    mode=$1; src=$2; dst=$3
    if [ ! -f "$src" ]; then
        echo "MISSING in the deployed tree: $src" >&2
        failed=1
        return
    fi
    # Silence when nothing differs, so the output of a deploy is the list of things that
    # actually changed rather than a wall to scroll past. A quiet run is the common case.
    if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
        return
    fi
    if install -m "$mode" "$src" "$dst"; then
        echo "  installed $dst"
        changed=1
        case "$dst" in
            /etc/systemd/system/*) units_changed=1 ;;
        esac
        case "$dst" in
            *.timer) timers="$timers $(basename "$dst")" ;;
        esac
    else
        echo "FAILED to install $dst" >&2
        failed=1
    fi
}

# The deployed tree is checked out from the bare repository and has no `.git` of its own, so
# the commit has to be read from there — `git -C /opt/sms-gate` answers "not a git repository"
# and the honest-looking "unknown commit" that produced was the very ambiguity this line
# exists to remove. safe.directory because the installer runs as root against a tree owned by
# the deploying account.
BARE=/opt/sms-gate.git
git_bare() { git -c safe.directory="$BARE" --git-dir="$BARE" "$@" 2>/dev/null; }

commit=$(git_bare rev-parse --short HEAD) || commit=""
if [ -n "$commit" ]; then
    echo "installing units from $commit"
    # The commit alone would still not say whether the tree *matches* it. It can fail to: a
    # push whose checkout did not complete, or a file edited in place on the server, both
    # leave a tree that the hash misdescribes — and being misdescribed confidently is worse
    # than being unknown.
    if [ -n "$(git_bare --work-tree=/opt/sms-gate status --porcelain --untracked-files=no)" ]; then
        echo "  WARNING: the deployed tree differs from $commit — installing what is on disk" >&2
    fi
else
    echo "installing units — could not read the deployed commit from $BARE" >&2
fi

install_one 755 "$SRC/alert-send.sh"                       /usr/local/sbin/sms-gate-alert

install_one 644 "$SRC/sms-gate.service"                    /etc/systemd/system/sms-gate.service
install_one 644 "$SRC/sms-gate-notify@.service"            /etc/systemd/system/sms-gate-notify@.service

install_one 755 "$SRC/wwan-backup/wwan-backup.sh"          /usr/local/sbin/wwan-backup
install_one 644 "$SRC/wwan-backup/wwan-backup.service"     /etc/systemd/system/wwan-backup.service
install_one 644 "$SRC/wwan-backup/wwan-watchdog.service"   /etc/systemd/system/wwan-watchdog.service
install_one 644 "$SRC/wwan-backup/wwan-watchdog.timer"     /etc/systemd/system/wwan-watchdog.timer

install_one 755 "$SRC/wg-watchdog/wg-tunnel-check.sh"      /usr/local/sbin/wg-tunnel-check
install_one 644 "$SRC/wg-watchdog/wg-tunnel-check.service" /etc/systemd/system/wg-tunnel-check.service
install_one 644 "$SRC/wg-watchdog/wg-tunnel-check.timer"   /etc/systemd/system/wg-tunnel-check.timer

if [ "$units_changed" = 1 ]; then
    systemctl daemon-reload
    echo "  daemon-reload"
    # Timers are restarted because a changed schedule is otherwise read only at boot, and a
    # timer restart costs nothing. Services are deliberately NOT restarted: `wwan-backup`
    # tears down the backup data session on stop, which during a wired outage would take the
    # only working uplink with it. The scripts those services run are re-executed on every
    # tick anyway, so installing the script is enough for them; a changed *unit* applies at
    # the next boot, and that is the honest trade.
    for t in $timers; do
        systemctl restart "$t" && echo "  restarted $t"
    done
fi

[ "$changed" = 0 ] && echo "  nothing to install"
exit "$failed"
