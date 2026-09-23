#!/bin/bash
# Укус сужения сторожа открытых верификаций — задача 7.2.
#
# Охраняемое стоит денег в один клик: владелец правит `ucaller_key` или
# `tg_gateway_token` на `/admin/`, и сторож в течение минуты валит КАЖДУЮ открытую
# платную верификацию с формулировкой «маршрут потерял предусловие, на котором был
# предложен», — при том что предусловие уже израсходовано: звонок размещён и оплачен,
# код прочитан.
#
# Три мутации, и третья — положительный контроль. Сторож, переставший перепроверять
# ВСЁ, охраняет ровно ничего: у `call_in` предусловие обязано держаться всё окно.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_verification_outcome_reaches_the_app.py"
MGR=$REPO/app/modem/manager.py

cd "$REPO" || exit 1
cp "$MGR" "$SCRATCH/manager.py.orig"
restore() { cp "$SCRATCH/manager.py.orig" "$MGR"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ \
         "$REPO"/app/modem/__pycache__ "$REPO"/app/verification/__pycache__ \
         "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -6
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$MGR" "$expr" <<'PYEOF'
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

# 1. Сужения нет вовсе — состояние до 23.09.2026. Обязаны покраснеть все четыре
#    сторожа 7.2: три платных рунга плюс сторож самой ГРАНИЦЫ.
mut "1. сужения нет — сторож перепроверяет всё" \
'        open_rows = [row for row in await queries.open_verifications_with_a_route()
                     if not placement.places_here(row["route"])]@@@        open_rows = await queries.open_verifications_with_a_route()'

# 2. Граница заведена ПЕРЕЧНЕМ в самом стороже — и заведена верно на сегодняшний день,
#    то есть поведение по всем трём платным рунгам не меняется. Это и есть тихий дрейф,
#    которого владелец запретил 23.09: `PLACED_HERE` ведётся по своей причине, перечень
#    здесь — по чужой, и разъедутся они молча. Обязан покраснеть РОВНО сторож границы,
#    и обязаны остаться зелёными три рунговых — иначе он косит не то.
mut "2. перечень рунгов вместо границы placement" \
'                     if not placement.places_here(row["route"])]@@@                     if row["route"] not in ("tg_gateway", "flash_call", "sms_out")]'

# 3. Положительный контроль, перевёрнутый: сторож перепроверяет РОВНО те рунги, которые
#    перепроверять не надо. Обязан покраснеть `call_in` — тот, ради которого норма и
#    писалась: у входящего звонка событие ещё впереди, и предусловие обязано держаться
#    всё окно. Без этой мутации мутация 1 зеленеет от сторожа, который не сторожит.
mut "3. граница перевёрнута — перепроверяются только исходящие" \
'                     if not placement.places_here(row["route"])]@@@                     if placement.places_here(row["route"])]'

restore
echo "== восстановлено; финальный прогон"
run
