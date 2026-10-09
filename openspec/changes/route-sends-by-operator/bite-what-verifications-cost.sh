#!/bin/bash
# Укус задач 6.9 и 6.10: во что обходятся верификации — ответимо ДО счёта вендора.
#
# Находка свипа 22.09.2026, и найдена как ОТСУТСТВИЕ, а не как дефект: три сценария
# требования «What verifications cost is visible before the bill is» не несли под собой
# ничего. `SUM(cost)` не встречался во всём `app/` ни разу; единственный агрегат
# (`queries.py:429`) — не про деньги.
#
# 🔴 Плата, не купившая ничего, — СЧЁТ, а не сумма: проверка способности, не ответившая
# внутри бюджета, могла подтвердиться и списаться, а `request_id` до нас не доехал.
# Складывать нечего — есть только число случаев. Сложенная со спендом, она была бы
# догадкой; выброшенная — балансом, который уезжает без причины.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_what_verifications_cost_is_answerable.py"
QR=$REPO/app/db/queries.py
RT=$REPO/app/admin/router.py
TPL=$REPO/app/admin/templates/stats.html
FILES="$QR $RT $TPL"

cd "$REPO" || exit 1
for f in $FILES; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in $FILES; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/admin/__pycache__ \
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

# 1. Плата, не купившая ничего, сложена со спендом. Числа у неё нет — значит сумма
#    получит ноль и будет выглядеть достоверной.
mut "1. возможно списанное сложено со спендом" "$QR" \
'               SUM(CASE WHEN r.outcome = ? THEN 1 ELSE 0 END)       AS possibly_charged
          FROM verification_rungs r
         WHERE r.route IN ({_PAID_PLACEHOLDERS}){where}
         GROUP BY r.route@@@               0                                                    AS possibly_charged
          FROM verification_rungs r
         WHERE (r.route IN ({_PAID_PLACEHOLDERS}) OR ? IS NULL){where}
         GROUP BY r.route'

# 2. Окно периода снято: «за последний месяц» отвечает всей историей.
mut "2. период не ограничивает ответ" "$QR" \
'    return " AND r.started_at > datetime('\''now'\'', ?)", [lower]@@@    return "", []'

# 3. Ответ есть, но на экран не попал: страница счётчиков его не спрашивает.
#    «Читаемо» — это экран, а не запрос.
mut "3. страница счётчиков не спрашивает спенд" "$RT" \
'            "spend": await queries.verification_spend(period),@@@            "spend": [],'

# 4. Экран потерял половину «кто потратил».
mut "4. таблица «кто потратил» не выводится" "$TPL" \
'  {% for s in spend_by_app %}@@@  {% for s in [] %}'

# 5. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: в ответ попадают и бесплатные рунги. Мутации выше он
#    удовлетворяет безупречно — и заводит строку с нулями под модемом, у которого нет
#    вендора, чтобы спросить «а это чей счёт».
mut "5. бесплатные рунги тоже в отчёте (контроль)" "$QR" \
'         WHERE r.route IN ({_PAID_PLACEHOLDERS}){where}
         GROUP BY r.route@@@         WHERE (r.route IN ({_PAID_PLACEHOLDERS}) OR 1 = 1){where}
         GROUP BY r.route'

restore
echo "== восстановлено; финальный прогон"
run
