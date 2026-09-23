#!/bin/bash
# Укус сторожа, который держит СВЯЗЬ кода с нормой, живущей в дельте соседа — задача 7.2.
#
# Сужение сторожа выкатывается с `route-sends-by-operator`, а норма, которую оно сужает,
# — ADDED-требование заявки `verify-by-inbound-contact`: там она написана и больше нигде
# не существует. В живой спеке её нет и не будет до архивации соседа.
#
# `openspec validate` слеп ко всему этому разом: он не читает прозу требования, не видит
# переименованного заголовка и молчит про `MODIFIED` требования, которого в живой спеке
# нет вовсе. Поэтому сторож — не памятка, а четыре мутации.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_sweep_narrowing_is_not_orphaned.py"
NEIGHBOUR=$REPO/openspec/changes/verify-by-inbound-contact/specs/phone-verification/spec.md
HERE=$REPO/openspec/changes/route-sends-by-operator/specs/phone-verification/spec.md
MGR=$REPO/app/modem/manager.py

cd "$REPO" || exit 1
cp "$NEIGHBOUR" "$SCRATCH/neighbour.md.orig"
cp "$HERE" "$SCRATCH/here.md.orig"
cp "$MGR" "$SCRATCH/manager.py.orig"
restore() {
  cp "$SCRATCH/neighbour.md.orig" "$NEIGHBOUR"
  cp "$SCRATCH/here.md.orig" "$HERE"
  cp "$SCRATCH/manager.py.orig" "$MGR"
}
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/modem/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -5
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

# 1. Заголовок требования у соседа переименован — ровно то, на чём `openspec validate`
#    молчит. Сужение остаётся сиротой: код уже, чем любая написанная норма.
mut "1. заголовок требования переименован у соседа" "$NEIGHBOUR" \
'### Requirement: A verification whose route stops working ends with a named reason, and a call that arrived during an outage is gone@@@### Requirement: A verification whose route stops working ends with a named reason'

# 2. Сужение из текста вынуто, заголовок цел. Требование читается снова обобщённо —
#    «любой рунг, потерявший предусловие», — и на размещённом рунге это значит завалить
#    звонок, который уже размещён и оплачен.
mut "2. сужение вынуто из прозы требования" "$NEIGHBOUR" \
'🔴 **On a rung this gateway places, the precondition SHALL NOT be re-proved once the rung has
been selected.**@@@🔴 **Placed rungs are covered too.**'

# 3. Требование заведено ВТОРОЙ раз — в дельте этой заявки. Архивируется первой она, и
#    старая обобщённая редакция приезжает в живую спеку поверх; сосед перезапишет её
#    позже, и чья возьмёт, решит порядок архивации, а не решение владельца.
mut "3. требование продублировано в дельте этой заявки" "$HERE" \
'### Requirement: A verification carried by the modem takes that message'"'"'s outcome@@@### Requirement: A verification whose route stops working ends with a named reason, and a call that arrived during an outage is gone

An open verification whose selected route has lost the precondition it was offered on SHALL be
terminated with that reason and the application notified.

#### Scenario: The route dies under an open verification
- **WHEN** an open verification'"'"'s selected route loses the precondition it was offered on
- **THEN** the verification ends with that reason

### Requirement: A verification carried by the modem takes that message'"'"'s outcome'

# 4. Код перестал спрашивать `placement` — граница нормы и граница кода разъехались.
#    Поведение при этом СОВПАДАЕТ с верным на сегодняшний день: это тихий дрейф, а не
#    поломка, и поймать его можно только здесь.
mut "4. код читает свой перечень вместо названной границы" "$MGR" \
'                     if not placement.places_here(row["route"])]@@@                     if row["route"] not in ("tg_gateway", "flash_call", "sms_out")]'

restore
echo "== восстановлено; финальный прогон"
run
