#!/bin/bash
# Укус нормы 4.62: per-number лимиты РЕШАЮТСЯ И БЕРУТСЯ ОДНИМ АКТОМ.
#
# Находка круга критики 22.09.2026. Гейт спрашивал, сколько номер уже потратил, а
# строка ЭТОЙ попытки писалась только после прохода всех гейтов — и две
# верификации на один номер (капабилити их прямо разрешает) обе читали пустую
# историю, обе проходили и обе били вендора внутри пятнадцатисекундного зазора.
# Бронь маршрута не закрывает: она ключуется на верификации, а их две.
#
# 🔴 Цена не второй звонок, а блокировка номера у вендора на ДЕСЯТЬ ЧАСОВ.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_numbers_limits_are_taken_in_one_act.py"
LD=$REPO/app/verification/ladder.py
LM=$REPO/app/verification/limits.py
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
for f in "$LD" "$LM" "$QR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$LD" "$LM" "$QR"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. ДЕФЕКТ КАК НАЙДЕН: платный рунг снова пишется безусловной строкой, а лимиты
#    остаются вопросом, который кто-то должен был положить в список гейтов.
mut "1. платный рунг пишется безусловно (дефект как найден)" "$LD" \
'        if route in PAID_ROUTES:@@@        if False:'

# 2. 🔴 МУТАЦИЯ, РАДИ КОТОРОЙ ВЕСЬ ФАЙЛ: условия те же и лимит на месте, но
#    решение и запись разъехались на два оператора. Между ними встаёт вторая
#    сопрограмма — ровно тот зазор, который норма закрывает. Тест, который
#    проверял бы «лимит существует», остался бы зелёным.
mut "2. решение и запись — два оператора вместо одного" "$QR" \
'    cursor = await db.execute(
        "INSERT INTO verification_rungs (verification_id, route, outcome) "
        "SELECT ?, ?, ? "
        # The three limits, one clause each and one statement for all of them. Kept on
        # separate lines with the limit each enforces named, so that a mutation can drop
        # exactly one of them and a reader can see which is missing.
        f" WHERE ({_PAID_FOR_NUMBER}) = 0 "   # the gap since the last attempt
        f"   AND ({_PAID_FOR_NUMBER}) < ? "   # the ceiling per rolling minute
        f"   AND ({_PAID_FOR_NUMBER}) < ?",   # the ceiling per rolling window
        (verification_id, route, outcome,
         *_for_number(phone, verification_id, gap_seconds),
         *_for_number(phone, verification_id, 60), per_minute,
         *_for_number(phone, verification_id, window_seconds), per_day),
    )@@@    async with db.execute(
        f"SELECT ({_PAID_FOR_NUMBER}) = 0 "
        f"   AND ({_PAID_FOR_NUMBER}) < ? "
        f"   AND ({_PAID_FOR_NUMBER}) < ?",
        (*_for_number(phone, verification_id, gap_seconds),
         *_for_number(phone, verification_id, 60), per_minute,
         *_for_number(phone, verification_id, window_seconds), per_day),
    ) as probe:
        allowed = await probe.fetchone()
    if not allowed or not allowed[0]:
        return None
    cursor = await db.execute(
        "INSERT INTO verification_rungs (verification_id, route, outcome) "
        "VALUES (?, ?, ?)",
        (verification_id, route, outcome),
    )'

# 3. Счёт видит СОБСТВЕННЫЕ рунги этой верификации. Лестница клеймит второй
#    платный рунг, когда строке первого ноль секунд от роду, — и перестаёт
#    двигаться вовсе. Все соседние сторожа при этом зелены: они ходят по
#    лестнице из одного рунга.
mut "3. счёт видит собственные рунги лестницы" "$QR" \
'f" WHERE v.phone = ? AND r.verification_id <> ? AND r.route IN ({_PAID_PLACEHOLDERS}) "@@@f" WHERE v.phone = ? AND (r.verification_id <> ? OR 1=1) AND r.route IN ({_PAID_PLACEHOLDERS}) "'

# 4. Отказ клейма проигнорирован: рунга нет, а вендора всё равно спрашивают.
mut "4. отказ клейма проигнорирован" "$LD" \
'            if rung_id is None:@@@            if False:'

# 5. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ. Клейм, отказывающий всем, удовлетворяет «вендора
#    спросили один раз» безупречно. Без этой мутации весь файл пуст.
mut "5. клейм отказывает всем (контроль)" "$LM" \
'    if rung_id is not None:@@@    if False:'

restore
echo "== восстановлено; финальный прогон"
run
