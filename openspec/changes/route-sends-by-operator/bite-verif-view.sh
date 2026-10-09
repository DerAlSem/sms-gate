#!/bin/bash
# Укус экрана ВЕРИФИКАЦИЙ в консоли — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-verif-view.sh` как на основание пяти мутаций, а файла не
# существовало ни в одном коммите, достижимом из любого рефа.
#
# Главная из пяти — первая. `verifications_for_phone` перечисляет колонки, а не
# звёздочкой, и это ГАРАНТИЯ, а не стиль: `SELECT *` отдал бы живой секрет в шаблон,
# на том единственном экране, где номер абонента стоит рядом с его перепиской.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_admin_verifications.py"
QR=$REPO/app/db/queries.py
AR=$REPO/app/admin/router.py
TPL=$REPO/app/admin/templates/messages.html

cd "$REPO" || exit 1
for f in "$QR" "$AR" "$TPL"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$QR" "$AR" "$TPL"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. 🔴 Запрос звёздочкой вместо перечня колонок. Код доезжает до шаблона, и экран,
#    на котором он появится, — тот самый, где номер стоит рядом с перепиской.
mut "1. запрос звёздочкой" "$QR" \
'        "SELECT id, app_id, status, route, confirmed_by, reason, attempts, "
        "       created_at, expires_at, confirmed_at "
        "  FROM verifications WHERE phone = ? "@@@        "SELECT * "
        "  FROM verifications WHERE phone = ? "'

# 2. Номер перестаёт отбирать: на экране одного человека показываются чужие
#    верификации.
mut "2. номер не отбирает" "$QR" \
'        "  FROM verifications WHERE phone = ? "@@@        "  FROM verifications WHERE (phone = ? OR 1=1) "'

# 3. Ни один рунг не доезжает до страницы — а рунг и есть всё объяснение того, почему
#    верификация кончилась так, как кончилась.
mut "3. рунги не доезжают до страницы" "$AR" \
'            rungs = await queries.rungs_for_verifications([v["id"] for v in verifications])@@@            rungs = {}'

# 4. Блок не наполняется вовсе: запросы отработали, на экране пусто.
mut "4. блок не наполняется" "$AR" \
'            verifications = await queries.verifications_for_phone(open_phone)@@@            verifications = []'

# 5. Строка теряет якорь, по которому её находит сторож. Мутация служебная и
#    названа честно: она доказывает, что сторож ищет именно строку верификации, а не
#    любое совпадение слова на странице.
mut "5. строка теряет якорь" "$TPL" \
'          <tr id="verification-{{ v.id }}">@@@          <tr>'

restore
echo "== восстановлено; финальный прогон"
run
