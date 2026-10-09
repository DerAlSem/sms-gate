#!/bin/bash
# Укус сторожей 4.17e — подметания исхода, доехавшего после границы лестницы.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_call_outcome_that_arrives_late.py tests/test_verification_outcome_reaches_the_app.py"
FC=$REPO/app/verification/flash_carrier.py
DP=$REPO/app/verification/dispatch.py
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
for f in "$FC" "$DP" "$QR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$FC" "$DP" "$QR"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Подметание не зовётся вовсе — рунг снова умирает «истёкшим».
mut "1. подметание не зовётся" "$DP" \
'    settled = await flash_carrier.resolve_outstanding()@@@    settled = 0; _ = flash_carrier'

# 2. Подметание ПОСЛЕ истечения — «expired» обгоняет вендорский ответ и врёт человеку.
mut "2. подметание после истечения" "$DP" \
'    settled = await flash_carrier.resolve_outstanding()
    if settled:
        logger.info("Settled %d outstanding call rung(s)", settled)

    # Expire what is due.@@@    # Expire what is due.'

# 3. Недозвон не закрывает открытую верификацию — человек досиживает окно.
mut "3. недозвон не закрывает верификацию" "$FC" \
'    if still_open:@@@    if False:'

# 4. Стоимость не записывается — неделя спенда разойдётся с балансом.
mut "4. стоимость не записана" "$FC" \
'    await queries.set_rung_outcome(row["rung_id"], outcome=ladder.FAILED, cost=info.cost,@@@    await queries.set_rung_outcome(row["rung_id"], outcome=ladder.FAILED, cost=None,'

# 5. Нерешённый ответ вендора прочитан как решённый — рунг закрыт выдумкой.
mut "5. нерешённое прочитано как решённое" "$FC" \
'    if not ucaller.resolved(info):@@@    if False:'

# 6. Помещённый звонок прочитан как провал — верификация закрыта на живом звонке.
mut "6. помещённый звонок = провал" "$FC" \
'    if info.call_status == ucaller.PLACED and not _digits_changed(info.code, code or ""):@@@    if False:'

# 7. Возраст рунга не ограничен — вендора дёргают вечно, раз в подметание. Мутируется
#    аргумент, а не сам SQL: в якоре из queries.py живут одинарные кавычки, а их в
#    одинарно закавыченном аргументе bash не бывает.
mut "7. возраст рунга не ограничен" "$FC" \
'            FLASH_CALL, within_seconds=store.verification_ttl_seconds):@@@            FLASH_CALL, within_seconds=10 ** 9):'

# 8. Подметание берёт чужие рунги — не только те, что вендор не решил.
mut "8. берём рунги любого исхода" "$QR" \
'" WHERE r.route = ? AND r.outcome = ? AND r.vendor_ref IS NOT NULL "@@@" WHERE r.route = ? AND r.outcome IS NOT ? AND r.vendor_ref IS NOT NULL "'

# 9. Исключение вендора роняет весь проход, который объявляет ВСЕ прочие концовки.
mut "9. исключение вендора роняет проход" "$FC" \
'        except Exception:
            logger.exception("verification %s: settling the call rung %s raised",
                             row["verification_id"], row["vendor_ref"])@@@        except Exception:
            raise'

# 10. Пустой кредитал не останавливает — подметание ходит к вендору без ключа.
mut "10. ходим без кредитала" "$FC" \
'    if not bearer:
        return 0

    settled = 0@@@    bearer = bearer or "x"
    settled = 0'

# 11. Баланс наблюдается ДО списания и в подметании тоже.
mut "11. баланс до списания в подметании" "$FC" \
'    balance.observe(FLASH_CALL, info.balance_after)

    still_open@@@    balance.observe(FLASH_CALL, info.balance_before)

    still_open'

restore
echo "== восстановлено; финальный прогон"
run
