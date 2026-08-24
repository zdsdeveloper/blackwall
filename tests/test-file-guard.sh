#!/usr/bin/env bash
# Exercises bin/blackwall-file-guard against the things that can be left at a
# predictable path: symlinks, FIFOs, devices, directories, oversized files,
# files or parent directories other users can write to.
#
# Run it from anywhere:  ./tests/test-file-guard.sh
#
# Everything happens in a throwaway directory under $HOME -- the guard refuses
# paths outside $HOME and world-writable parents, so /tmp is not usable here.

set -u

GUARD="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bin/blackwall-file-guard"
[[ -f $GUARD ]] || { echo "guard not found at $GUARD" >&2; exit 1; }

T=$(mktemp -d "$HOME/.cache/blackwall-guard-test.XXXXXX")
trap 'rm -rf "$T"' EXIT
cd "$T" || exit 1

pass=0 fail=0
chk() { if [[ $2 == "$3" ]]; then echo "  ok   $1"; ((pass++)); else echo "  FAIL $1 (expected $2, got $3)"; ((fail++)); fi; }
same() { if [[ $2 == "$3" ]]; then echo "  ok   $1"; ((pass++)); else echo "  FAIL $1 (got '$3')"; ((fail++)); fi; }

# Every call is wrapped in `timeout`: a guard that hangs is itself the bug.
g() { timeout 5 "$GUARD" "$@"; }

echo "state file (allow-symlink=0, reclaim=1)"
printf '{"deadline":42}\n' | g write "$T/state" 65536 0 1; chk "writes"  0 $?
same "roundtrips" '{"deadline":42}' "$(g read "$T/state" 65536 0 0)"
same "written 0600" 600 "$(stat -c %a "$T/state")"
g read "$T/absent" 65536 0 0 2>/dev/null;                  chk "missing file reports absent" 10 $?

echo "a symlink planted at the state path"
echo PRECIOUS > "$T/victim"; rm -f "$T/state"; ln -s "$T/victim" "$T/state"
g read "$T/state" 65536 0 0 2>/dev/null;                   chk "read refuses it" 11 $?
printf '{"deadline":7}\n' | g write "$T/state" 65536 0 1;  chk "write takes the name back" 0 $?
same "link target untouched" PRECIOUS "$(cat "$T/victim")"
[[ -L $T/state ]] && { echo "  FAIL link survived"; ((fail++)); } || { echo "  ok   link replaced"; ((pass++)); }

echo "a FIFO planted at the state path"
rm -f "$T/fifo"; mkfifo "$T/fifo"
g read "$T/fifo" 65536 0 0 2>/dev/null;                    chk "read refuses without hanging" 11 $?
printf 'x\n' | g write "$T/fifo" 65536 0 1;                chk "write takes the name back" 0 $?
[[ -p $T/fifo ]] && { echo "  FAIL fifo survived"; ((fail++)); } || { echo "  ok   fifo replaced"; ((pass++)); }

echo "config file (allow-symlink=1, reclaim=0)"
echo '{"persistAcrossReboot":false}' > "$T/dotfile"; ln -s "$T/dotfile" "$T/cfg"
same "reads through a vetted symlink" '{"persistAcrossReboot":false}' "$(g read "$T/cfg" 65536 1 0)"
printf 'ROUNDTRIP\n' | g write "$T/cfg" 65536 1 0;         chk "writes through it" 0 $?
[[ -L $T/cfg ]] && same "target updated, link kept" ROUNDTRIP "$(cat "$T/dotfile")" \
                || { echo "  FAIL link destroyed"; ((fail++)); }

echo "a symlink that leaves \$HOME is refused in both directions"
ln -s /etc/hostname "$T/escape"
before=$(cat /etc/hostname)
g read "$T/escape" 65536 1 0 2>/dev/null;                  chk "read refused" 11 $?
printf 'EVIL\n' | g write "$T/escape" 65536 1 0 2>/dev/null; chk "write refused" 11 $?
same "/etc/hostname untouched" "$before" "$(cat /etc/hostname)"

echo "everything else that can sit at a path"
head -c 200000 /dev/zero > "$T/big"
g read "$T/big" 65536 0 0 2>/dev/null;                     chk "oversized file refused" 11 $?
ln -s /dev/zero "$T/dev"
g read "$T/dev" 65536 1 0 2>/dev/null;                     chk "device refused" 11 $?
mkdir -p "$T/adir"
g read "$T/adir" 65536 0 0 2>/dev/null;                    chk "directory refused" 11 $?
mkdir -p "$T/ow"; chmod 777 "$T/ow"; echo x > "$T/ow/f"
g read "$T/ow/f" 65536 0 0 2>/dev/null;                    chk "other-writable parent refused" 11 $?
echo x > "$T/owf"; chmod 646 "$T/owf"
g read "$T/owf" 65536 0 0 2>/dev/null;                     chk "other-writable file refused" 11 $?

echo "argument handling"
head -c 200000 /dev/zero | g write "$T/toobig" 65536 0 1 2>/dev/null; chk "oversized write refused" 12 $?
g read "relative/path" 65536 0 0 2>/dev/null;              chk "relative path refused" 12 $?
g bogus "$T/state" 65536 0 0 2>/dev/null;                  chk "unknown mode refused" 12 $?

echo
echo "$pass passed, $fail failed"
[[ $fail -eq 0 ]]
