#!/bin/bash
# Укус ШАБЛОНОВ текста верификации — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-template.sh` как на основание девяти мутаций, а файла не
# существовало ни в одном коммите, достижимом из любого рефа.
#
# Шаблон — текст, введённый ОПЕРАТОРОМ, и это решает здесь всё. Подстановка сделана
# `replace`, а не `str.format`, потому что форматтер прочитал бы всякую фигурную
# скобку как поле: `{0}` лезет в аргументы, `{a.b}` в атрибуты, — и опечатка в
# формулировке стала бы провалом отправки ровно в ту минуту, когда человек ждёт код.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_verification_template.py"
TP=$REPO/app/verification/template.py
SS=$REPO/app/settings_store.py

cd "$REPO" || exit 1
for f in "$TP" "$SS"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$TP" "$SS"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Шаблон БЕЗ места под код принят. Отправляется сообщение, в котором человеку
#    нечего набрать.
mut "1. шаблон без места под код принят" "$TP" \
'    if len(found) == 0:@@@    if False:'

# 2. Шаблон с ДВУМЯ местами принят. Код печатается дважды, и какое из двух мест
#    настоящее — вопрос к читателю сообщения.
mut "2. шаблон с двумя местами принят" "$TP" \
'    if len(found) > 1:@@@    if False:'

# 3. Неизвестное поле в фигурных скобках принято. Оно доедет до абонента как есть.
mut "3. неизвестное поле принято" "$TP" \
'    if unknown:@@@    if False:'

# 4. Пустой шаблон принят: сообщение, в котором нечего читать.
mut "4. пустой шаблон принят" "$TP" \
'    if not text.strip():@@@    if False:'

# 5. Одно приложение названо дважды. Который из двух шаблонов победит, решил бы
#    порядок списка — невидимо.
mut "5. приложение названо дважды" "$TP" \
'        if app_id in seen:@@@        if False:'

# 6. 🔴 Нечитаемая настройка прочитана как ОТСУТСТВИЕ шаблонов — то есть тихо, а не
#    отказом с алертом. Разница между «оператор чинит настройку» и «приложения молча
#    перестали слать коды».
mut "6. нечитаемая настройка = отсутствие шаблонов" "$TP" \
'        raise UnreadableTemplates(
            f"the stored verification templates are not JSON: {exc}") from exc@@@        return {}'

# 7. 🔴 Подстановка делается ФОРМАТТЕРОМ. Опечатка оператора в формулировке
#    превращается в провал отправки в ту минуту, когда человек ждёт код, а `{a.b}`
#    в шаблоне становится чтением атрибутов.
mut "7. подстановка форматтером" "$TP" \
'    return text.replace("{" + CODE + "}", code)@@@    return text.format(**{CODE: code})'

# 8. Проводка в слой настроек снята на ПРОВЕРКЕ: шаблон сохраняется каким угодно.
mut "8. проверка не подключена к настройкам" "$SS" \
'    if type_ == "templates":
        from app.verification import template
        template.validate(raw)
        return@@@    if type_ == "templates":
        return'

# 9. Проводка снята на НОРМАЛИЗАЦИИ: вставленное значение хранится с пробелами и
#    матчится вокруг них вечно.
mut "9. нормализация не подключена к настройкам" "$SS" \
'    if type_ == "templates":
        from app.verification import template
        return template.normalize(raw)@@@    if type_ == "templates":
        return raw'

restore
echo "== восстановлено; финальный прогон"
run
