#!/bin/bash
# Укус: номер, заблокированный ПОСЛЕ открытия верификации, не доходит до вендора.
#
# Окно шириной в TTL верификации — пять минут. Дверь открытия блокировку
# спрашивает, дверь выбора не спрашивала, и внутри окна лестница ставила
# ПЛАТНЫЙ звонок на номер, который шлюз решил не трогать вовсе.
#
# Мутация 4 — та, ради которой заведён сторож на границу: она переносит проверку
# из связки гейтов в дверь выбора. Краснеют ДВА теста, и оба по делу:
#   - сторож на инвариант — потому что в связке гейтов проверки больше нет, и
#     следующая дверь в платную лестницу её не унаследует;
#   - сторож «с двери» — потому что дверной отказ оставляет верификацию
#     ОТКРЫТОЙ, а гейт её заканчивает: маршрут был затребован до обхода, и
#     `placement.place` валит верификацию с названной причиной. То есть
#     перенос — не эквивалентная перестановка, он меняет и то, что видит
#     человек: у него остаётся висеть верификация, за которой ничего не идёт.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_call_rung_is_reachable.py"
GT=$REPO/app/verification/gates.py
RT=$REPO/app/api/router.py

cd "$REPO" || exit 1
for f in "$GT" "$RT"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$GT" "$RT"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/api/__pycache__ \
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

# 1. Гейт не собран в платную лестницу — возврат к состоянию до этой правки.
mut "1. гейт не собран" "$GT" \
'    return (blacklist_gate(phone), entitlement_gate(app_id), ceiling_gate())@@@    return (entitlement_gate(app_id), ceiling_gate())'

# 2. Гейт собран, но никогда не отказывает.
mut "2. гейт никогда не отказывает" "$GT" \
'        if await queries.is_phone_blocked(phone):@@@        if False:'

# 3. Гейт отказывает ВСЕГДА — положительный контроль наоборот: шлюз, который
#    не верифицирует никого.
mut "3. гейт отказывает всегда" "$GT" \
'        if await queries.is_phone_blocked(phone):@@@        if True:'

# 4. 🔴 Проверка перенесена из связки гейтов в дверь выбора — см. шапку.
#    Собирается из двух правок сразу, поэтому идёт мимо `mut`.
restore
$PY - "$RT" <<'PYEOF'
import sys
path = sys.argv[1]
s = open(path, encoding='utf-8').read()
old = """    if row["status"] != "pending":"""
new = """    if await queries.is_phone_blocked(row["phone"]):
        raise HTTPException(status_code=422,
                            detail={"error": "blacklist", "phone": row["phone"]})
    if row["status"] != "pending":"""
assert s.count(old) == 1
open(path, 'w', encoding='utf-8').write(s.replace(old, new, 1))
PYEOF
$PY - "$GT" <<'PYEOF'
import sys
path = sys.argv[1]
s = open(path, encoding='utf-8').read()
old = "        if await queries.is_phone_blocked(phone):"
new = "        if False:  # перенесено в дверь мутацией укуса"
assert s.count(old) == 1
open(path, 'w', encoding='utf-8').write(s.replace(old, new, 1))
PYEOF
echo "== 4. проверка перенесена в дверь (гейт выключен, дверь проверяет)"
run

restore
echo "== восстановлено; финальный прогон"
run
