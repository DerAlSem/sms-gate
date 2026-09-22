#!/bin/bash
# Укус сторожей 4.1 — правило, перенацеленное МЕЖДУ размещением и отправкой.
#
# Мутация 4 — та, ради которой сторож и заведён: она оставляет зелёным соседний
# сторож 4.17b (там правило всё ещё называет модем, вторым) и краснит только новый.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_modem_rung_carries_a_code.py"
MG=$REPO/app/modem/manager.py

cd "$REPO" || exit 1
cp "$MG" "$SCRATCH/manager.py.orig"
restore() { cp "$SCRATCH/manager.py.orig" "$MG"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/modem/__pycache__ \
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

# 1. Оговорки нет вовсе — отправитель перерешает то, что решила лестница.
mut "1. оговорки нет" "$MG" \
'        if await queries.verification_of_message(msg.message_id) is not None:
            return False@@@        if False:
            return False'

# 2. Оговорка расширена на всё — свободный текст уезжает в модем по правилу,
#    которое увело оператора с него целиком.
mut "2. оговорка пропускает всех" "$MG" \
'        if await queries.verification_of_message(msg.message_id) is not None:
            return False@@@        if True:
            return False'

# 3. Отправитель идёт по записи правила дальше первого рунга, подбирая подходящий.
mut "3. идём дальше первого рунга" "$MG" \
'        assigned = assigned_routes[0]@@@        assigned = assigned_routes[-1]'

# 4. 🔴 Оговорка сужена до «правило всё ещё где-то называет модем». Сторож 4.17b
#    остаётся ЗЕЛЁНЫМ — там правило называет модем вторым, — и краснеет только
#    сторож на перенацеленное правило. Ради этой мутации он и написан.
mut "4. оговорка требует, чтобы правило ещё называло модем" "$MG" \
'        if await queries.verification_of_message(msg.message_id) is not None:
            return False@@@        if await queries.verification_of_message(msg.message_id) is not None:
            _op = await self._operator_for(msg.phone)
            if routes.SMS_OUT in rule.route_for(_op):
                return False'

restore
echo "== восстановлено; финальный прогон"
run
