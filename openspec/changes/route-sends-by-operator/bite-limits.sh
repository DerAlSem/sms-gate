#!/bin/bash
# Укус механизма per-number лимитов — того самого, чья ошибка стоит абоненту
# ДЕСЯТИ ЧАСОВ без возможности войти куда бы то ни было.
#
# 🔴 Этот скрипт заведён 22.09.2026 по решению владельца, и вот почему он
# заведён поздно: норма в спеке ссылалась на `bite-limits.sh` как на своё
# основание, а такого файла не существовало НИКОГДА — ни в рабочем дереве, ни в
# одном коммите, достижимом из любого рефа. Семь названных мутаций не
# прогонялись ничем. Ссылка на укус — такое же утверждение о коде, как всякое
# другое, и проверяется так же.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_per_number_limits.py"
LM=$REPO/app/verification/limits.py
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
for f in "$LM" "$QR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$LM" "$QR"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run
echo "   (час по UTC сейчас: $(date -u +%H) — читай примечание к мутации 5)"

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

# 1. Окно считает только звонковый рунг. Лестница переходит с телеграма на
#    звонок и проходит потолок, которого на самом деле достигла, — а телеграм
#    своих лимитов не публикует вовсе, ловить нечем.
mut "1. считаем только звонковый рунг" "$QR" \
'_PAID_ROUTE_VALUES = tuple(sorted(PAID_ROUTES))@@@_PAID_ROUTE_VALUES = ("flash_call",)'

# 2. Пауза между двумя попытками снята. Блокирует вендора именно частота, а не
#    объём, так что это самая дешёвая дорога к десяти часам.
mut "2. пауза снята" "$LM" \
'        if ages[0] < gap:@@@        if False:'

# 3. Минутный потолок снят.
mut "3. минутный потолок снят" "$LM" \
'        if in_a_minute >= store.verification_per_minute:@@@        if False:'

# 4. Суточный потолок снят.
mut "4. суточный потолок снят" "$LM" \
'        if len(ages) >= store.verification_per_day:@@@        if False:'

# 5. Календарный день вместо скользящего окна. База хранит наивный UTC, вендор
#    русский: календарный день, прочитанный не в той зоне, сбрасывает счётчик на
#    три часа раньше вендорского — и в эти три часа шлюз уверенно ставит звонок,
#    стоящий абоненту десять часов.
#    ⚠️ ЕДИНСТВЕННАЯ мутация здесь, кусающаяся не круглые сутки, и это свойство
#    САМОГО теста, а не мутации: он ставит попытки на 20 часов назад, и под
#    календарным днём они оказываются «вчера» лишь пока час по UTC меньше 20.
#    После 20:00 UTC мутация зелёная законно. Строка выше печатает текущий час,
#    чтобы прогон нельзя было прочитать неправильно.
mut "5. календарный день вместо скользящего окна" "$QR" \
'"   AND r.started_at > datetime('"'"'now'"'"', ? || '"'"' seconds'"'"') "@@@"   AND r.started_at > date('"'"'now'"'"') AND ? IS NOT NULL "'

# 6. Вендорские числа зашиты в код вместо настроек. Числа не наши, вендор меняет
#    их не спросив, и тогда лечение — выкатка вместо сохранения.
mut "6. вендорские числа зашиты" "$LM" \
'        in_a_minute = sum(1 for age in ages if age < 60)
        if in_a_minute >= store.verification_per_minute:@@@        in_a_minute = sum(1 for age in ages if age < 60)
        if in_a_minute >= 4:'

# 7. Номер не участвует в отборе — все номера считаются как один. Лимит,
#    заведённый защищать АБОНЕНТА, начинает отказывать по чужому трафику.
mut "7. все номера как один" "$QR" \
'" WHERE v.phone = ? AND r.route IN ({_PAID_PLACEHOLDERS}) "@@@" WHERE (v.phone = ? OR 1=1) AND r.route IN ({_PAID_PLACEHOLDERS}) "'

restore
echo "== восстановлено; финальный прогон"
run
