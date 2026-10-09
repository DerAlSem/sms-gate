#!/bin/bash
# Укус задачи 6.7: у каждого `expired` названо ПОЛЕ, из которого он пришёл.
#
# Находка свипа 22.09.2026. В этой способности слово `expired` несут два РАЗНЫХ поля, и
# значат они разное: истечение ДОСТАВКИ — плата возвращается и до абонента не дошло
# ничего; истечение ВЕРИФИКАЦИИ — закрылось окно кода, и о доставке с деньгами оно не
# говорит ничего. Записанные голым словом, оба приезжали в одну строку консоли
# (`admin/templates/messages.html:171`) из двух несвязанных фактов.
#
# Требование (`specs/phone-verification/spec.md:426`) запрещает записывать и действовать
# на голый `expired` прямым текстом; леджер, спутавший эти два, вернул бы деньги за
# доставленное или взял бы за недоставленное.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_tg_callback.py"
CB=$REPO/app/verification/tg_callback.py
QR=$REPO/app/db/queries.py
FILES="$CB $QR"

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

# 1. Дефект как найден: исход рунга пишется словом вендора как есть.
mut "1. исход рунга пишется голым словом (дефект как найден)" "$CB" \
'        outcome=_outcome_word(status.delivery_status), reason=note, refunded=refunded)@@@        outcome=status.delivery_status or "unknown", reason=note, refunded=refunded)'

# 2. Вторая половина той же пары: собственное окно снова пишет голый `expired` в
#    `reason` — слово, которое статус уже сказал, и то же, которым вендор говорит о деньгах.
mut "2. окно пишет голый expired в reason" "$QR" \
"        f\"UPDATE verifications SET status = 'expired', reason = 'window_expired', \"@@@        f\"UPDATE verifications SET status = 'expired', reason = 'expired', \""

# 3. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: переименование срабатывает на ЧЁМ УГОДНО. Обе мутации выше
#    оно удовлетворяет безупречно — и теряет остальные слова вендора (`delivered`,
#    `read`, `revoked`), то есть чинит имя ценой факта.
mut "3. переименовано всё подряд (контроль)" "$CB" \
'    if delivery_status == "expired":@@@    if delivery_status:'

restore
echo "== восстановлено; финальный прогон"
run
