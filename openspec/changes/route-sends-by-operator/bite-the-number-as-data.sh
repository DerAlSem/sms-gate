#!/bin/bash
# Укус: номер, который абонент должен набрать или написать, отдаётся ДАННЫМИ.
#
# Норма не про опрятность ответа. `instruction` английская и переводу нами не
# подлежит — gettext в app/verification нет вовсе, — поэтому приложению с
# русскими пользователями оставалось выковыривать цифры регуляркой из нашей
# прозы. Это сделало бы нашу формулировку НЕГЛАСНОЙ частью контракта, которая
# ломается в день, когда кто-то улучшит предложение.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_call_rung_is_reachable.py"
RT=$REPO/app/verification/routes.py
SC=$REPO/app/api/schemas.py
AR=$REPO/app/api/router.py

cd "$REPO" || exit 1
for f in "$RT" "$SC" "$AR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$RT" "$SC" "$AR"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/api/__pycache__ "$REPO"/app/db/__pycache__ \
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

# 1. Поле не доезжает до двери — собирается в Offer и теряется в ответе. Ровно
#    та форма, в которой «реализовано» оказывается «недостижимо».
mut "1. поле не доезжает до двери" "$AR" \
'        status="pending",
        routes=[RouteOffer(route=o.route, instruction=o.instruction, number=o.number)@@@        status="pending",
        routes=[RouteOffer(route=o.route, instruction=o.instruction)'

# 2. Номер отдаётся на ВСЕХ рунгах. Приложение получает адрес там, где действует
#    шлюз, и может позвать человека звонить туда, где его не ждут.
mut "2. номер отдаётся на всех рунгах" "$RT" \
'        if name not in _NEEDS_GATEWAY_NUMBER:
            return None@@@        if False:
            return None'

# 3. Поле расходится с прозой: данные говорят одно, предложение другое. Хуже
#    отсутствия поля — приложение доверится данным.
mut "3. поле расходится с прозой" "$RT" \
'        return self._gateway_number or None@@@        return (self._gateway_number or "")[:-1] or None'

# 4. Поле перестаёт быть аддитивным: обязательное без умолчания. Потребитель,
#    собирающий RouteOffer сам, ломается на ровном месте.
mut "4. поле обязательное, не аддитивное" "$SC" \
'    number: str | None = None@@@    number: str | None'

restore
echo "== восстановлено; финальный прогон"
run
