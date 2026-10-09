#!/bin/bash
# Укус: рунг, зовущий вендора дважды, не тратит потолок лестницы дважды.
#
# Задача 4.63, находка круга критики 22.09.2026.
#
# Норма говорила «каждый носитель применяет потолок к своим вендорским вызовам»,
# и этой фразе удовлетворяет реализация, выдающая каждому вызову ВЕСЬ остаток.
# Ровно так и было в `tg_carrier`: `seconds_left` считался один раз на входе и
# уходил и в `checkSendAbility`, и в `sendVerificationMessage`. Сосед
# `flash_carrier` под той же нормой берёт дедлайн и тратит остаток.
#
# Мутация 2 — про то, почему у этого сторожа есть положительный контроль:
# «второй меньше первого» удовлетворяется и полом в 0.1 с, который ломает рунг
# целиком. Сторож на одно неравенство был бы дырой в свою сторону.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_bound_is_a_deadline_not_a_duration.py"
TC=$REPO/app/verification/tg_carrier.py

cd "$REPO" || exit 1
cp "$TC" "$SCRATCH/tg_carrier.py.orig"
restore() { cp "$SCRATCH/tg_carrier.py.orig" "$TC"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$TC" "$expr" <<'PYEOF'
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

# 1. Исходный дефект: отправке снова выдаётся вся длительность.
mut "1. отправке выдан весь потолок (исходный дефект)" \
'            callback_url=callback_url, sender_username=sender_username,
            timeout=max(0.1, deadline - time.monotonic()))@@@            callback_url=callback_url, sender_username=sender_username,
            timeout=max(0.1, seconds_left))'

# 2. «Второй меньше первого», удовлетворённое полом — рунг сломан целиком.
mut "2. отправка прижата к полу 0.1 с" \
'            callback_url=callback_url, sender_username=sender_username,
            timeout=max(0.1, deadline - time.monotonic()))@@@            callback_url=callback_url, sender_username=sender_username,
            timeout=0.1)'

# 3. Дедлайн взят нулевым — потолка нет вовсе.
mut "3. дедлайн нулевой" \
'        deadline = time.monotonic() + max(0.0, seconds_left)@@@        deadline = time.monotonic()'

# 4. Проверке выдан пол вместо остатка — половина, которую ловит контроль.
mut "4. проверке выдан пол вместо остатка" \
'            phone, token=token, timeout=max(0.1, deadline - time.monotonic()))@@@            phone, token=token, timeout=0.1)'

echo
echo "== восстановление и контроль: снова обязано быть зелёным"
restore
run
