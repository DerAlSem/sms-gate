#!/bin/bash
# Укус нормы «трафик вендорского отказа НЕ уезжает на модем» — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-modem.sh` как на основание пяти мутаций, а файла не
# существовало ни в одном коммите, достижимом из любого рефа.
#
# Норма сформулирована как ОТСУТСТВИЕ автоматического failover, и это важно: модем
# достижим, и положительный контроль это доказывает. Утверждение — «пройденные рунги
# суть в точности ответ `rule.route_for` и ничего сверх него». Запасной путь,
# дописанный шлюзом самому себе, проявился бы здесь рунгом, которого правило не
# называло.
#
# Удержание модема, названного правилом, — соседняя норма, и её кусает
# `bite-withhold.sh`.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_vendor_failure_spares_the_modem.py"
LD=$REPO/app/verification/ladder.py
CR=$REPO/app/verification/tg_carrier.py
TG=$REPO/app/verification/tg_gateway.py

cd "$REPO" || exit 1
for f in "$LD" "$CR" "$TG"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$LD" "$CR" "$TG"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Модем дописан в хвост ходки — автоматический failover ровно в той форме, в
#    которой его и пишут.
mut "1. модем дописан в хвост ходки" "$LD" \
'    for route in rungs:@@@    for route in list(rungs) + [SMS_OUT]:'

# 2. Модем пробуется ТОЛЬКО когда ничего не понесло — хитрая разновидность того же
#    failover, и именно под неё построен стенд: второй платный рунг отказывает по
#    умолчанию, иначе лестница остановилась бы раньше и дописанный хвост никогда бы
#    не достигался.
mut "2. модем пробуется, когда ничего не понесло" "$LD" \
'    reason = _why_nothing_carried(attempts)
    await queries.fail_verification(verification_id, reason=reason)
    return Walk(reason=reason, attempts=tuple(attempts))@@@    if SMS_OUT not in rungs and SMS_OUT in carriers:
        await carriers[SMS_OUT](phone, seconds_left=1.0, rung_id=0)
    reason = _why_nothing_carried(attempts)
    await queries.fail_verification(verification_id, reason=reason)
    return Walk(reason=reason, attempts=tuple(attempts))'

# 3. Отказ вендора и неразмещаемый отказ проходят молча. С двумя платными рунгами
#    «который из вендоров» — это первый вопрос оператора, и ответ на него чтением
#    лога есть разница между двухминутным пополнением и отключением.
mut "3. отказ вендора не будит оператора" "$CR" \
'_LOUD = frozenset({tg_gateway.REFUSED, tg_gateway.UNCLASSIFIED})@@@_LOUD = frozenset()'

# 4. Неразмещаемый отказ (а деньги кончаются ИМЕННО так — строки ошибки у этого
#    случая нет ни в одном из десяти снимков) прочитан как отказ абонента.
mut "4. неразмещаемый отказ = отказ абонента" "$TG" \
'    return UNCLASSIFIED@@@    return DECLINED'

# 5. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: всякий отказ вендора прочитан как отказ НАМ, включая
#    «этого абонента нет в телеграме». Тогда модем, названный правилом, удерживается
#    и у обычного отказа абонента, и норма из узкой становится тотальной — а
#    работающий модем перестаёт работать.
mut "5. любой отказ = отказ нам (контроль)" "$TG" \
'    if error in FATAL_ERRORS:
        return REFUSED
    if error in DECLINE_ERRORS:@@@    return REFUSED
    if error in DECLINE_ERRORS:'

restore
echo "== восстановлено; финальный прогон"
run
