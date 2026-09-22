#!/bin/bash
# Укус задачи 6.13: учётные данные вендора НЕ живут в окружении.
#
# 🔴 Аннотация требования (`specs/outbound-routing/spec.md:181-262`) обещала «seven
# mutations» за средовую половину — а укуса, гоняющего
# `tests/test_credentials_do_not_live_in_the_environment.py`, не было ни в одном из
# 27 `bite-*.sh`, ни в `bite-code.py`, ни в 414 коммитах истории. Это ВТОРОЙ случай того
# же дефекта в этой заявке (первый — `phone-verification/spec.md:623`), и оба раза
# ссылка на укус была утверждением о коде, которое никто не проверял.
#
# Поверхностей окружения ДВЕ, и они ломаются по-разному: `os.environ` в `app/` и
# `BaseSettings(env_file=".env")` в `app/config.py`, где чтение делает pydantic и ни
# одного `os.environ` для переписи нет. Поэтому мутации идут парами по поверхностям.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_credentials_do_not_live_in_the_environment.py"
SS=$REPO/app/settings_store.py
CF=$REPO/app/config.py
TC=$REPO/app/verification/tg_carrier.py
FILES="$SS $CF $TC"

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

# --- поверхность 1: `os.environ` и старшинство строки над переменной ------------------

# 1. Окружение снова старше строки: `.env`, положенный после первого старта, доезжает до
#    вендора. Это дефект, ради которого написано требование.
mut "1. окружение перекрывает существующую строку" "$SS" \
'        if spec.key in existing:
            continue@@@        if False:
            continue'

# 2. Пустая строка переписывается из окружения. Пустая строка — состояние, в котором
#    эстейт приезжает: её пишет первый же старт, и со второго `.env` обязан быть потерян
#    даже там, где никто ничего не настраивал.
mut "2. пустая строка переписывается из окружения" "$SS" \
'        existing = {row["key"] async for row in cur}@@@        existing = {row["key"] async for row in cur if row["value"]}'

# 3. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: не сеется вообще ничего. Мутации 1-2 такой сеятель
#    удовлетворяет безупречно — и оставляет свежий эстейт без единого ключа.
mut "3. не сеется вообще ничего (контроль)" "$SS" \
'    for spec, raw in candidates:@@@    for spec, raw in []:'

# 4. Санкционированный читатель перестал читать окружение. Перепись «ровно один
#    читатель» после этого проходит ВПУСТУЮ, и именно это её вторая половина ловит.
mut "4. сеятель больше не читает окружение (перепись впустую)" "$SS" \
'        env_val = os.environ.get(spec.key.upper())@@@        env_val = None'

# 5. Второй читатель окружения — «для удобства», в несущем рунге. Атрибутное написание.
mut "5. второй читатель окружения, написание os.environ" "$TC" \
'def carrier(
    verification_id: int, *, app_id: str, token: str, callback_url: str,@@@def _convenience_read():
    import os
    return os.environ.get("TG_GATEWAY_TOKEN")


def carrier(
    verification_id: int, *, app_id: str, token: str, callback_url: str,'

# 6. То же чтение, но написанием `from os import getenv` — перепись снята с синтаксиса
#    именно затем, чтобы написание её не обходило.
mut "6. второй читатель окружения, написание getenv" "$TC" \
'def carrier(
    verification_id: int, *, app_id: str, token: str, callback_url: str,@@@from os import getenv


def _convenience_read():
    return getenv("TG_GATEWAY_TOKEN")


def carrier(
    verification_id: int, *, app_id: str, token: str, callback_url: str,'

# --- поверхность 2: `.env` читает pydantic, и `os.environ` там нет вовсе --------------

# 7. Учётные данные вендора объявлены в `.env`-настройках. Ни одного `os.environ` — для
#    переписи поверхности 1 этого не существует; читается на каждом старте, на странице
#    настроек невидимо, без рестарта не меняется.
mut "7. вендорский токен объявлен в .env-настройках" "$CF" \
'    # --- Storage ---@@@    tg_gateway_token: str = ""

    # --- Storage ---'

restore
echo "== восстановлено; финальный прогон"
run
