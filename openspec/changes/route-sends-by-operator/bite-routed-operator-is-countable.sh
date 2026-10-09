#!/bin/bash
# Укус задачи 6.8: «поехало без известного оператора» СЧИТАЕТСЯ и на платных рунгах.
#
# Находка свипа 22.09.2026. Требование (`specs/outbound-routing/spec.md:295-298`) просит
# записывать этот случай, «so that the case is countable rather than invisible», — а
# считать его было нечем: верификация, которую понесли `tg_gateway` или `flash_call`,
# строки в `messages` не создаёт вовсе, и пара `routed_route`/`routed_operator` на той
# таблице отвечает только за то, что отправил модем.
#
# Слово, а не NULL: NULL не отличает «поехало ни за кого» от «строка старше колонки», и
# число, по которому пересматривают правило, тихо включило бы всю историю.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_ladder_walk.py"
LD=$REPO/app/verification/ladder.py
QR=$REPO/app/db/queries.py
FILES="$LD $QR"

cd "$REPO" || exit 1
for f in $FILES; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in $FILES; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Дефект как найден: ходка не записывает оператора вовсе.
mut "1. ходка не записывает оператора (дефект как найден)" "$LD" \
'    await queries.record_verification_routing(verification_id, operator=operator)@@@    pass'

# 2. Неизвестный пишется NULL-ом. Считать по NULL нельзя: он же значит «строка старше
#    колонки», и число включит всю историю, ничего об этом не сказав.
mut "2. неизвестный оператор пишется NULL-ом" "$QR" \
'        (operator or ROUTED_WITHOUT_A_KNOWN_OPERATOR, verification_id),@@@        (operator, verification_id),'

# 3. Запись после отказов. Случай, выпадающий из счёта ровно тогда, когда его отказали, —
#    это та же невидимость, ради которой клауза написана.
mut "3. запись после отказа правила" "$LD" \
'    await queries.record_verification_routing(verification_id, operator=operator)

    if rule.refuses(list(rungs)):@@@    if not rule.refuses(list(rungs)):
        await queries.record_verification_routing(verification_id, operator=operator)

    if rule.refuses(list(rungs)):'

# 4. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: пишется всегда `?`, известный оператор теряется. Мутации 1-3
#    такая запись удовлетворяет, а число «поехало без оператора» делает равным всему.
mut "4. известный оператор тоже пишется как ? (контроль)" "$QR" \
'        (operator or ROUTED_WITHOUT_A_KNOWN_OPERATOR, verification_id),@@@        (ROUTED_WITHOUT_A_KNOWN_OPERATOR, verification_id),'

restore
echo "== восстановлено; финальный прогон"
run
