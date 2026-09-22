#!/bin/bash
# Укус вендорских УЧЁТНЫХ ДАННЫХ в консоли — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-credentials.sh` как на основание четырёх мутаций, а
# файла не существовало ни в одном коммите, достижимом из любого рефа.
#
# Сторож перечисляет учётные данные по ФОРМЕ ключа (`_token`, `_key`, `_secret`,
# `_password`), а не по имени, поэтому ключ uCaller покрывается им сам собой, когда
# приезжает. Мутации бьют по трём слоям — объявление, вид, страница, — потому что
# секрет уезжает на экран на любом из них.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_vendor_credentials.py"
SS=$REPO/app/settings_store.py
AR=$REPO/app/admin/router.py
TPL=$REPO/app/admin/templates/settings.html

cd "$REPO" || exit 1
for f in "$SS" "$AR" "$TPL"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$SS" "$AR" "$TPL"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Токен объявлен НЕ секретом. Дальше всё работает «правильно» — и печатает его.
mut "1. токен объявлен не секретом" "$SS" \
'    Spec("tg_gateway_token", "str", "", "Verification", True,@@@    Spec("tg_gateway_token", "str", "", "Verification", False,'

# 2. Вид отдаёт значение дальше. Объявление на месте, экран — нет.
mut "2. вид отдаёт значение секрета" "$AR" \
'            "value": "" if spec.is_secret else current,@@@            "value": current,'

# 3. Страница рисует `value=` секретному полю. Тип `password` прячет символы от
#    взгляда и не прячет ничего от исходного кода страницы.
mut "3. страница рисует value= секрету" "$TPL" \
'            <input name="{{ f.key }}" id="set-{{ f.key }}" type="password" placeholder="{{ _('"'"'configured (blank = keep)'"'"') if f.configured else _('"'"'not set'"'"') }}">@@@            <input name="{{ f.key }}" id="set-{{ f.key }}" type="password" value="{{ f.value }}" placeholder="{{ _('"'"'configured (blank = keep)'"'"') if f.configured else _('"'"'not set'"'"') }}">'

# 4. Страница перестаёт отличать «заведено» от «не заведено». Оператор не может
#    узнать, настроен ли рунг, не перезаписав учётные данные вслепую.
mut "4. заведено и не заведено неразличимы" "$AR" \
'            "configured": bool(current) if spec.is_secret else None,@@@            "configured": None,'

restore
echo "== восстановлено; финальный прогон"
run
