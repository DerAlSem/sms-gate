#!/bin/bash
# Укус УДЕРЖАНИЯ модема — решение владельца 20.09.2026, задача 4.60.
#
# 🔴 Спека ссылалась на `bite-withhold.sh` как на основание шести мутаций, а файла не
# существовало ни в одном коммите, достижимом из любого рефа.
#
# Норма узкая, и узость здесь — всё. Отказ ВЕНДОРА нам (ротированный токен, пустой
# счёт) общешлюзовой: он откажет каждой верификации, и все в ту же минуту. Понести их
# модемом — значит превратить отключение одного вендора в поток трафика на маршрут, от
# которого эта капабилити и существует чтобы уводить, а для абонента МегаФона это
# маршрут, который ему отказывает: приложение прочитает доставку, человек получит
# тишину.
#
# Отказ АБОНЕНТА — противоположный случай: это утверждение об одном человеке, а не о
# шлюзе, и модем за ним обязан продолжать работать. Мутация 2 — про норму, тянущуюся
# слишком далеко, и она краснит ровно положительный контроль.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_vendor_failure_spares_the_modem.py"
LD=$REPO/app/verification/ladder.py

cd "$REPO" || exit 1
cp "$LD" "$SCRATCH/ladder.py.orig"
restore() { cp "$SCRATCH/ladder.py.orig" "$LD"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$LD" "$expr" <<'PYEOF'
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

# 1. Удержание снято вовсе — возврат к состоянию до решения владельца.
mut "1. удержание снято" \
'        if route in _MODEM_ROUTES and any(a.outcome == REFUSED for a in attempts):@@@        if False:'

# 2. 🔴 Норма тянется слишком далеко: модем удерживается и после отказа АБОНЕНТА.
#    Краснеет положительный контроль — и это ровно то, ради чего он написан: без него
#    вся строгость выше прошла бы на модемном носителе, до которого ничто никогда не
#    добирается, и узость нормы осталась бы намерением, а не замеренным фактом.
mut "2. удержание и после отказа абонента" \
'        if route in _MODEM_ROUTES and any(a.outcome == REFUSED for a in attempts):@@@        if route in _MODEM_ROUTES and any(a.outcome in (REFUSED, DECLINED) for a in attempts):'

# 3. Удержание применяется к КАЖДОЙ модемной ходке, без всякого отказа вендора.
mut "3. модем удерживается всегда" \
'        if route in _MODEM_ROUTES and any(a.outcome == REFUSED for a in attempts):@@@        if route in _MODEM_ROUTES:'

# 4. Удержанный рунг не записан. Рунг, исчезнувший из списка строк, — это верификация,
#    у провала которой нет причины ни на одном экране.
mut "4. удержанный рунг не записан" \
'            await queries.record_verification_rung(
                verification_id, route=route, outcome=WITHHELD)@@@            pass'

# 5. Удержание поднимает ВТОРОЙ алерт на то же событие. Отказ, вызвавший удержание,
#    уже разбудил оператора с названным вендором, и второй сигнал на одно событие —
#    это шум, который хоронит первый.
mut "5. удержание поднимает второй алерт" \
'            attempts.append(Attempt(
                outcome=WITHHELD, route=route,@@@            from app.alerting import notify
            notify("routing", f"the modem rung {route} was withheld")
            attempts.append(Attempt(
                outcome=WITHHELD, route=route,'

# 6. Причина провала не называет рунги и их исходы — и «expired», сказанное человеку,
#    у которого удержали модем, сообщает единственное, чего не происходило.
mut "6. причина не называет удержанный рунг" \
'    return "no rung carried this verification: " + ", ".join(@@@    return "no rung carried this verification" or ", ".join('

restore
echo "== восстановлено; финальный прогон"
run
