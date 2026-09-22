#!/bin/bash
# Укус сторожей рунга flash_call (4.17): носитель, исход `unresolved` у лестницы и
# регистрация — проба, карта носителей, инструкция. Мутация ломает охраняемое, сторож
# обязан покраснеть.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_flash_call_carrier.py tests/test_the_call_rung_is_reachable.py tests/test_ladder_walk.py"
FC=$REPO/app/verification/flash_carrier.py
LD=$REPO/app/verification/ladder.py
PB=$REPO/app/verification/probes.py
PL=$REPO/app/verification/placement.py
RO=$REPO/app/verification/routes.py

cd "$REPO" || exit 1
for f in "$FC" "$LD" "$PB" "$PL" "$RO"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$FC" "$LD" "$PB" "$PL" "$RO"; do
  cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
# Трап восстанавливает, а не только убирает: скрипт, убитый на середине (SIGPIPE от
# `| head`, Ctrl-C), иначе оставляет мутацию в рабочем дереве. Замер: случилось.
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/api/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() { # name file python-expr
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

# --- носитель ------------------------------------------------------------------------
# 1. Нерешённый исход объявлен помещённым звонком — верификация «поехала», хотя вендор молчит.
mut "1. unresolved прочитан как carried" "$FC" \
'                outcome=ladder.UNRESOLVED, vendor_ref=vendor_ref,@@@                outcome=ladder.CARRIED, vendor_ref=vendor_ref,'

# 2. Нерешённый исход объявлен провалом — человеку сказали «кода не будет», а телефон звонит.
mut "2. unresolved прочитан как failed" "$FC" \
'                outcome=ladder.UNRESOLVED, vendor_ref=vendor_ref,@@@                outcome=ladder.FAILED, vendor_ref=vendor_ref,'

# 3. call_status: 0 прочитан как помещённый звонок.
mut "3. недозвон прочитан как carried" "$FC" \
'        if info.call_status == ucaller.PLACED:@@@        if info.call_status != ucaller.PLACED:'

# 4. Граница взята не лестницы, а вендорская (до минуты) — человек смотрит в спиннер.
#    Мутация растягивает, а не снимает границу: снятая целиком даёт вечный цикл, и укус
#    вешается вместо того, чтобы краснеть.
mut "4. граница вендорская, а не лестницы" "$FC" \
'        deadline = time.monotonic() + max(0.0, seconds_left)@@@        deadline = time.monotonic() + max(0.0, seconds_left) * 20'

# 5. Чужие цифры приняты: матчим код, который вендор не набирал.
mut "5. чужие цифры приняты (initCall)" "$FC" \
'        if _digits_changed(placed.code, code):@@@        if False:'

# 6. То же на втором чтении — getInfo.
mut "6. чужие цифры приняты (getInfo)" "$FC" \
'        if _digits_changed(info.code, code):@@@        if False:'

# 7. id авторизации не записан — платёж некому приписать и не по чему спросить.
mut "7. vendor_ref не записан" "$FC" \
'        await queries.set_rung_outcome(
            rung_id, outcome=ladder.ATTEMPTING, vendor_ref=vendor_ref,@@@        await queries.set_rung_outcome(
            rung_id, outcome=ladder.ATTEMPTING, vendor_ref=None,'

# 8. Пустой ucaller_id прочитан как успех.
mut "8. авторизация без id = успех" "$FC" \
'        if placed is None or placed.ucaller_id is None:@@@        if placed is None:'

# 9. Баланс наблюдается ДО списания — пол сработает на верификацию позже.
mut "9. наблюдаем баланс до списания" "$FC" \
'        balance.observe(FLASH_CALL, info.balance_after)@@@        balance.observe(FLASH_CALL, info.balance_before)'

# 10. Ушедшая верификация всё равно оплачивается.
mut "10. платим за ушедшую верификацию" "$FC" \
'        if not code:@@@        if False:'

# 11. Отказ вендора *нам* прочитан как отказ абоненту — лестница поедет по модему в грозу.
mut "11. отказ нам = decline" "$FC" \
'    ucaller.REFUSED: ladder.REFUSED,@@@    ucaller.REFUSED: ladder.DECLINED,'

# 12. Оператора не будят при отказе вендора.
mut "12. отказ вендора молча" "$FC" \
'        if call.kind in _LOUD:
            _alert(call)@@@        if False:
            _alert(call)'

# --- лестница ------------------------------------------------------------------------
# 13. СНЯТА как инертная, и это находка укуса, а не его пробел. Добавление UNRESOLVED в
#     `_ADVANCING` не меняет ничего: `_TAKEN_AND_PENDING` проверяется РАНЬШЕ и выходит
#     первым, так что членство UNRESOLVED в `_ADVANCING` — недостижимое условие, а не
#     сторожимое место. Мутация 14 покрывает ровно ту ветку, которая решает.

# 14. unresolved падает в ветку «принял и сломался» — верификация закрыта провалом.
mut "14. unresolved проваливает верификацию" "$LD" \
'_TAKEN_AND_PENDING = frozenset({UNRESOLVED})@@@_TAKEN_AND_PENDING = frozenset()'

# --- регистрация ---------------------------------------------------------------------
# 15. Проба снята — рунг не предлагается, хотя ключ есть.
mut "15. проба flash_call не зарегистрирована" "$PB" \
'        FLASH_CALL: _flash_call_probe(ucaller_bearer),
@@@'

# 16. Проба держится ни на чём — рунг предлагается на пустом кредитале.
mut "16. проба держится без кредитала" "$PB" \
'        if not bearer:
            return Proof(holds=False, reason="no uCaller credential is held")@@@        if False:
            return Proof(holds=False, reason="no uCaller credential is held")'

# 17. Носителя нет в карте — рунг выбран, и никто его не ставит (дефект 4.56).
mut "17. носителя нет в карте" "$PL" \
'        carriers[FLASH_CALL] = flash_carrier.carrier(
            verification_id, app_id=app_id, bearer=bearer)@@@        pass'

# 18. Рунг не объявлен ставящимся здесь.
mut "18. flash_call не ставится здесь" "$PL" \
'PLACED_HERE = frozenset({TG_GATEWAY, FLASH_CALL, SMS_OUT})@@@PLACED_HERE = frozenset({TG_GATEWAY, SMS_OUT})'

# 19. Инструкция пуста — рунг назван, а человеку не сказано ничего.
mut "19. инструкция рунга пуста" "$RO" \
'    FLASH_CALL: "Wait for a call to the number being verified and read the code off the "
                "calling number: it is the last four digits. Do not answer the call.",
@@@'

restore
echo "== восстановлено; финальный прогон"
run
