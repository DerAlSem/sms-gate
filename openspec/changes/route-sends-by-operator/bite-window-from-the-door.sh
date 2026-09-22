#!/bin/bash
# Укус сторожей 4.12 — вендорское окно по номеру, увиденное С ДВЕРИ.
#
# Механизм (limits + gates + walk) уже был покусан `bite-limits.sh` против лестницы с
# поддельным носителем. Здесь кусается ровно то, чего тот укус спросить не мог: живой
# HTTP через реестр, правило и placement, а считается `ucaller.init_call` — метод,
# который тратит деньги и запускает вендорскую блокировку на десять часов.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_call_rung_is_reachable.py"
LM=$REPO/app/verification/limits.py
GT=$REPO/app/verification/gates.py
LD=$REPO/app/verification/ladder.py
PL=$REPO/app/verification/placement.py
RT=$REPO/app/api/router.py
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
for f in "$LM" "$GT" "$LD" "$PL" "$RT" "$QR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$LM" "$GT" "$LD" "$PL" "$RT" "$QR"; do
  cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/app/api/__pycache__ \
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

# 1. Лимит по номеру не берётся при записи рунга — вендор узнаёт свой лимит сам.
#    🔴 С 22.09.2026 (задача 4.62) он не гейт в списке, а условие того самого
#    оператора, который пишет строку платного рунга: отсюда и мутация.
mut "1. лимит по номеру не берётся" "$LD" \
'        if route in PAID_ROUTES:@@@        if False:'

# 2. Дверь зовёт лестницу с пустым списком гейтов — та самая забывчивость, ради
#    невозможности которой `for_paid_ladder` и существует.
mut "2. дверь передаёт гейты пустыми" "$PL" \
'        gates=gates.for_paid_ladder(app_id, phone, rungs),@@@        gates=(),'

# 3. Гейты перечисляются, но не исполняются.
mut "3. гейты не исполняются" "$LD" \
'    for gate in gates:
        refusal = await gate()@@@    for gate in ():
        refusal = await gate()'

# 4. Отказ гейта прочитан и проигнорирован — лестница идёт дальше и звонит.
mut "4. отказ гейта проигнорирован" "$LD" \
'            return Walk(refused_by=refusal)@@@            pass'

# 5. Пауза между двумя попытками снята — остаются только потолки, а блокирует вендора
#    именно частота. Клауза SQL, а не ветвь на Python: с 4.62 решение и запись —
#    один оператор.
mut "5. пауза между попытками снята" "$QR" \
'f" WHERE ({_PAID_FOR_NUMBER}) = 0 "   # the gap since the last attempt@@@f" WHERE (({_PAID_FOR_NUMBER}) = 0 OR 1=1) "   # the gap since the last attempt'

# 6. Отказ больше не называет, сколько ждать: человеку сказано «нельзя» без «когда».
mut "6. отказ не называет паузу" "$LM" \
'        return f"too_soon: wait {wait}s before asking again"@@@        return "too_soon"'

# 7. Окно считается по одному рунгу вместо обоих платных — лестница переходит с
#    телеграма на звонок и проходит потолок, которого на самом деле достигла.
mut "7. окно считает один рунг" "$QR" \
'_PAID_ROUTE_VALUES = tuple(sorted(PAID_ROUTES))@@@_PAID_ROUTE_VALUES = ("tg_gateway",)'

# 8. Дверь отвечает отказ двухсотым — потребителю придётся опрашивать, чтобы узнать
#    правду о запросе, которого никто не ставил.
mut "8. отказ отвечен как успех" "$RT" \
'    if walk.refused_by and walk.carried_by is None:
        # Refused before any rung was contacted@@@    if False:
        # Refused before any rung was contacted'

# 9. Отказанная верификация остаётся открытой с занятым маршрутом и ничем поставленным.
mut "9. отказанная верификация висит" "$PL" \
'        await queries.fail_verification(verification_id, reason=reason)
        logger.info("verification %d: %s was selected and refused by %s; nothing was "@@@        logger.info("verification %d: %s was selected and refused by %s; nothing was "'

# 10. Наш отказ записан рунгом — попадает в счёт того, что делали вендоры, и заодно
#     съедает оба потолка.
mut "10. наш отказ записан рунгом" "$LD" \
'            logger.info("verification %d: refused before any rung, by %s",
                        verification_id, refusal)@@@            logger.info("verification %d: refused before any rung, by %s",
                        verification_id, refusal)
            await queries.record_verification_rung(
                verification_id, route=rungs[0], outcome=REFUSED)'

# 11. Положительный контроль наоборот: клейм, отказывающий всегда, — шлюз, который
#     верифицирует каждый номер ровно один раз.
mut "11. клейм отказывает всегда" "$LM" \
'    if rung_id is not None:@@@    if False:'

restore
echo "== восстановлено; финальный прогон"
run
