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
RT=$REPO/app/api/router.py
OP=$REPO/app/lookup/operator.py
FILES="$MG $RT $OP"

cd "$REPO" || exit 1
for f in $FILES; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in $FILES; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/modem/__pycache__ \
         "$REPO"/app/api/__pycache__ "$REPO"/app/lookup/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() { mutf "$1" "$MG" "$2"; }

mutf() {
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

# --- 6.4: то же решение на ДВЕРИ верификации ----------------------------------------
# Находка свипа 22.09.2026. Решение «протухшая строка берётся как есть, а бюджет тратится
# только там, где оператора нет вовсе» отправитель принимал верно, а дверь — нет: она
# звала `record_operator` безусловно, и строка возрастом 400 дней держала
# `POST /verifications` три секунды. Бюджетом при этом оказывался `voxlink_timeout` —
# терпение одного HTTP-вызова, — а не маршрутный бюджет.

# 3. Дефект как найден: дверь снова обновляет протухшее сама и без маршрутного бюджета.
mutf "3. дверь зовёт резолвер безусловно (дефект как найден)" "$RT" \
'    await resolve_within_bound(body.phone)@@@    await record_operator(body.phone)'

# 4. Бюджет снят: ждём столько, сколько терпит сам резолвер.
mutf "4. маршрутный бюджет снят" "$OP" \
'        await asyncio.wait_for(record_operator(phone), timeout=bound)@@@        await record_operator(phone)'

# 5. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: резолвер не зовётся вовсе. Обе мутации выше он
#    удовлетворяет безупречно — и оставляет дверь выбора ходить по лестнице оператора,
#    которого никто никогда не разрешил.
mutf "5. дверь не разрешает оператора вообще (контроль)" "$OP" \
'    named = await cached_operator(phone)
    if named is not None:
        return named@@@    named = await cached_operator(phone)
    return named'

restore
echo "== восстановлено; финальный прогон"
run
