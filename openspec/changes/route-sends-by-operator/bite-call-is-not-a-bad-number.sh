#!/bin/bash
# Укус сторожей 4.21 (вторая половина) — недозвон не растит счётчик постоянных отказов.
#
# Сторож на ОТСУТСТВИЕ, поэтому мутация здесь обратная: не ломается охраняемое, а
# ВПИСЫВАЕТСЯ то, чего быть не должно. Сторож, который не краснеет от вписанного
# `record_permanent_fail`, охраняет пустоту — а зелёный он и в ненаписанном коде.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_a_failed_call_is_not_a_bad_number.py"
FC=$REPO/app/verification/flash_carrier.py
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
for f in "$FC" "$QR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$FC" "$QR"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" file="$2" expr="$3"
  restore
  $PY - "$file" "$expr" <<'PYEOF'
import sys
path, expr = sys.argv[1], sys.argv[2]
s = open(path, encoding='utf-8').read()
old, new = expr.split('@@@')
assert s.count(old) == 1, f"anchor hit {s.count(old)} times: {old[:60]!r}"
open(path, 'w', encoding='utf-8').write(s.replace(old, new, 1))
PYEOF
  if [ $? -ne 0 ]; then echo "!! $name: якорь не нашёлся"; return; fi
  echo "== $name"
  run
}

# 1. Недозвон в лестнице засчитан номеру — пять звонков, и номер закрыт на все маршруты.
mut "1. носитель считает недозвон" "$FC" \
'        return ladder.Attempt(
            outcome=ladder.FAILED, vendor_ref=vendor_ref, cost=info.cost,
            reason="the vendor could not connect the call to this subscriber")@@@        await queries.record_permanent_fail(
            phone, "the call could not be connected", store.blacklist_threshold)
        return ladder.Attempt(
            outcome=ladder.FAILED, vendor_ref=vendor_ref, cost=info.cost,
            reason="the vendor could not connect the call to this subscriber")'

# 2. То же в подметании — путь, который забывают, потому что он пишется как «уборка».
mut "2. подметание считает недозвон" "$FC" \
'    await queries.set_rung_outcome(row["rung_id"], outcome=ladder.FAILED, cost=info.cost,
                                   reason=reason)@@@    _v = await queries.get_verification(row["verification_id"], row["app_id"])
    await queries.record_permanent_fail(_v["phone"], reason, store.blacklist_threshold)
    await queries.set_rung_outcome(row["rung_id"], outcome=ladder.FAILED, cost=info.cost,
                                   reason=reason)'

# 3. Успешный звонок ТРОГАЕТ счётчик модема. Направление неважно: счётчик не этого
#    рунга, и любая его запись отсюда — голос звонка о том, что узнал модем.
mut "3. дозвон трогает счётчик модема" "$FC" \
'            return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref=vendor_ref,
                                  cost=info.cost)@@@            await queries.record_permanent_fail(
                phone, "the call was placed", store.blacklist_threshold)
            return ladder.Attempt(outcome=ladder.CARRIED, vendor_ref=vendor_ref,
                                  cost=info.cost)'

# 4. Недозвон снимает блокировку — номер, закрытый модемом, открывается звонком.
mut "4. недозвон снимает блокировку" "$FC" \
'        return ladder.Attempt(
            outcome=ladder.FAILED, vendor_ref=vendor_ref, cost=info.cost,
            reason="the vendor could not connect the call to this subscriber")@@@        await queries.unblock_phone(phone)
        return ladder.Attempt(
            outcome=ladder.FAILED, vendor_ref=vendor_ref, cost=info.cost,
            reason="the vendor could not connect the call to this subscriber")'

# 5. Контроль наоборот: сам счётчик мёртв. Без него всё выше зеленеет против таблицы,
#    в которую никто никогда не пишет.
mut "5. счётчик модема мёртв" "$QR" \
'async def record_permanent_fail(phone: str, error: str, threshold: int) -> None:@@@async def record_permanent_fail(phone: str, error: str, threshold: int) -> None:
    return'

# 6. Блокировка не наступает на пороге — счётчик растёт, а дверь никого не отказывает.
mut "6. порог не блокирует" "$QR" \
'        WHERE phone = ? AND blocked_at IS NULL AND fail_count >= ?@@@        WHERE phone = ? AND blocked_at IS NULL AND fail_count >= ? + 1000000'

restore
echo "== восстановлено; финальный прогон"
run
