#!/bin/bash
# Укус задачи 6.2: НЕЧИТАЕМОЕ ПРАВИЛО на двери выбора — отказ, а не трассбек.
#
# Находка свипа 22.09.2026, воспроизведённая через дверь: `POST /verifications/{id}/route`
# отвечал 500, а верификация оставалась `pending` с заявленным маршрутом и пустыми
# рунгами — ровно то состояние, которое первая фраза требования запрещает по имени.
#
# `placement.ladder_from` был единственным читателем правила без `except UnreadableRule`:
# у отправителя (`app/modem/manager.py`) и у пробы (`app/verification/probes.py`) он есть.
# Мутация 2 — про то, почему «прочитать как пустое» не лечение: трафик отведённого
# оператора уходит обратно на маршрут, который его отвергает, и здесь этот маршрут ПЛАТНЫЙ.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_door_that_walks_the_ladder.py"
PL=$REPO/app/verification/placement.py

cd "$REPO" || exit 1
cp "$PL" "$SCRATCH/placement.py.orig"
restore() { cp "$SCRATCH/placement.py.orig" "$PL"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/api/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$PL" "$expr" <<'PYEOF'
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

# 1. Дефект как найден: исключение правила мимо охраны — уходит в дверь и становится 500.
#    Ловится другой класс, а не снимается `try`: снятый `try` оставил бы висящий `except`,
#    и файл перестал бы разбираться вовсе. Красное от синтаксиса — не укус, а поломка.
mut "1. исключение правила проходит мимо (дефект как найден)" \
'    except rule.UnreadableRule as exc:@@@    except ZeroDivisionError as exc:'

# 2. 🔴 Нечитаемое прочитано как ПУСТОЕ — соблазнительная починка, которую норма
#    отвергает теми же словами у двух других читателей. Пустым правило отправляет
#    трафик отведённого оператора обратно на отвергающий его маршрут, и здесь он платный.
mut "2. нечитаемое прочитано как пустое правило" \
'    named = rule.route_for(operator)@@@    try:
        named = rule.route_for(operator)
    except rule.UnreadableRule:
        named = []'

# 3. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: отказ стал безусловным. `try`, проглатывающий и читаемое
#    правило, удовлетворяет обеим мутациям выше безупречно — и не ставит ни одного рунга.
mut "3. отказано всегда, и читаемому тоже (контроль)" \
'        rungs = ladder_from(route, operator)@@@        rungs = ladder_from(route, operator)
        raise rule.UnreadableRule("bite: the rule is never readable")'

restore
echo "== восстановлено; финальный прогон"
run
