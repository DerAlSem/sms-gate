#!/bin/bash
# Укус записи МАРШРУТНОГО РЕШЕНИЯ на пути отправки — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-lookup.sh` как на основание двух мутаций, а файла не
# существовало ни в одном коммите, достижимом из любого рефа.
#
# Решение пишется отправителем ДО того, как он что-либо отдаёт модему, и на ОБОИХ
# исходах: и когда правило пропускает элемент на модем, и когда отказывает. Запись
# только на одном из них — это половина журнала, в которой не отличить «правило
# решило модем» от «правило не спрашивали».
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_send_path_operator_lookup.py"
MG=$REPO/app/modem/manager.py

cd "$REPO" || exit 1
cp "$MG" "$SCRATCH/manager.py.orig"
restore() { cp "$SCRATCH/manager.py.orig" "$MG"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/modem/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$MG" "$expr" <<'PYEOF'
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

# 1. Решение не записано на ПРОПУСКАЮЩЕЙ ветви: элемент уходит модемом, и нигде не
#    сказано, что модем назвало правило, а не отсутствие вопроса.
mut "1. решение не записано на пропускающей ветви" \
'        if assigned == routes.SMS_OUT:
            await queries.record_message_routing(
                msg.message_id, route=assigned, operator=operator)
            return False@@@        if assigned == routes.SMS_OUT:
            return False'

# 2. Решение не записано на ОТКАЗЫВАЮЩЕЙ ветви: у отказанного сообщения на экране не
#    остаётся ни маршрута, который его увёл, ни оператора, по которому увёл.
mut "2. решение не записано на отказывающей ветви" \
'        await queries.record_message_routing(
            msg.message_id, route=route, operator=operator)
        await refusals.record(@@@        await refusals.record('

restore
echo "== восстановлено; финальный прогон"
run
