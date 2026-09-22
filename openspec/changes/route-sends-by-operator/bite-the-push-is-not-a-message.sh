#!/bin/bash
# Укус задачи 6.14: пуш о верификации не читается приёмником как пуш о сообщении.
#
# 🔴 Аннотация требования (`specs/phone-verification/spec.md:752`) обещала «five
# mutations bite, including one that moves the message contract underneath it» — а
# гонял их никто: `bite-late-call-outcome.sh` берёт тот же файл тестов, но про ПОЗДНИЙ
# ИСХОД ЗВОНКА, и формы рассылки не касается ни одной мутацией. Второй случай того же
# дефекта после 6.13 в этой же заявке.
#
# Оба тела приезжают на ОДИН URL, и `id` — то, чем старший контракт называет свой
# предмет; слова `failed` и `expired` есть у обоих. Приёмник, ключённый на `id` и
# `status` — а это и есть весь старший контракт, — отметит чужое сообщение.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_verification_outcome_reaches_the_app.py"
VD=$REPO/app/verification/dispatch.py
MD=$REPO/app/modem/delivery_dispatch.py
FILES="$VD $MD"

cd "$REPO" || exit 1
for f in $FILES; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in $FILES; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/modem/__pycache__ \
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

# 1. Дефект как он был: предмет снова едет в `id`. Приёмник старшего контракта отметит
#    сообщение с этим номером — а номера сталкиваются с первой строки обеих таблиц.
mut "1. предмет снова едет в id (дефект как был)" "$VD" \
'            "verification_id": verification_id,@@@            "id": verification_id,'

# 2. Предмет едет в поле, которого у сообщения нет, но имя которого приёмник читает как
#    идентификатор сообщения. Сравнение двух тел этого поймать не может — ловит только
#    требование «ровно одно поле, и его имя говорит, что это».
mut "2. предмет едет в message_id" "$VD" \
'            "verification_id": verification_id,@@@            "message_id": verification_id,'

# 3. Номер едет ДВАЖДЫ: правильное поле на месте, и рядом второе. «Ровно одно место» —
#    не педантизм: второе поле читает кто-то другой, и читает как своё.
mut "3. номер едет в двух полях" "$VD" \
'            "verification_id": verification_id,@@@            "verification_id": verification_id,
            "ref": verification_id,'

# 4. Тело перестало называть себя. `object` не спасает приёмник, который в него не
#    смотрит, — но его отсутствие отнимает единственное, чем тела различимы намеренно.
mut "4. тело не называет свой род" "$VD" \
'            "object": "verification",@@@            "object": "message",'

# 5. 🔴 Контракт СООБЩЕНИЯ уехал под сторожем: старший контракт переименовал свой
#    предмет. Сторож сравнивает тела друг с другом, а не с памятью о теле сообщения, —
#    и обязан сказать «контракт сообщения переехал, перечитай этот тест», а не молча
#    зазеленеть на сравнении, потерявшем смысл.
mut "5. контракт сообщения переехал под сторожем (id -> message_id)" "$MD" \
'            "id": message_id,@@@            "message_id": message_id,'

restore
echo "== восстановлено; финальный прогон"
run
