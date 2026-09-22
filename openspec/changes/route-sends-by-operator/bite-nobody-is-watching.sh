#!/bin/bash
# Укус нормы 4.65: «за балансом этого вендора не следит никто» отвечается БЕЗ события
# и говорится так же громко, как сам пол.
#
# Находка круга критики 22.09.2026, канал выбран владельцем в тот же день: проверка на
# старте плюс `notify`. Оба состояния «не следит никто» уходили в `logger.warning`,
# тогда как пол, к которому они относятся, будит оператора, — а лог читают, когда уже
# подозревают. Хуже того, `observe` срабатывает, только когда баланс ПРИШЁЛ, то есть
# когда рунг уже несёт; рунг, которым ещё не пользовались, молчал вовсе, а норма
# написана именно про него.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_balance_floor.py"
BL=$REPO/app/verification/balance.py
MN=$REPO/app/main.py

cd "$REPO" || exit 1
for f in "$BL" "$MN"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$BL" "$MN"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Проверки на старте нет вовсе — возврат к состоянию, в котором рунг, которым ещё
#    не пользовались, не говорит ничего. Это ровно тот случай, про который норма.
mut "1. на старте никто не спрашивает" "$MN" \
'    await verification_balance.report_unwatched_rungs()@@@    pass'

# 2. Проверка есть и зовётся ПОСЛЕ yield — то есть на выключении, когда ответ уже
#    никому не нужен. Мутация из двух правок (снять отсюда, вставить туда), поэтому
#    идёт мимо `mut`.
restore
$PY - "$MN" <<'PYEOF2'
import sys
path = sys.argv[1]
s = open(path, encoding='utf-8').read()
call = "    await verification_balance.report_unwatched_rungs()\n"
assert s.count(call) == 1
s = s.replace(call, "", 1)
assert s.count("\n    yield\n") == 1
s = s.replace("\n    yield\n", "\n    yield\n" + call, 1)
open(path, 'w', encoding='utf-8').write(s)
PYEOF2
echo "== 2. проверка зовётся на выключении"
run

# 3. Проверка на старте говорит в лог вместо канала оператора.
mut "3. старт говорит в лог, а не оператору" "$BL" \
'        logger.warning("%s is configured and %s is not set; nobody is watching its "
                       "balance", vendor, floor_key)
        notify("routing", _unwatched_text(vendor, floor_key),
               dedup_extra=f"balance_unwatched:{route}")@@@        logger.warning("%s is configured and %s is not set; nobody is watching its "
                       "balance", vendor, floor_key)'

# 4. Ненастроенный рунг тоже докладывается. Рунг без учётных данных не предлагается
#    вовсе и не тратит ничего; доклад о нём на каждом старте учит игнорировать канал,
#    который несёт и «вендор кончается».
mut "4. ненастроенный рунг тоже докладывается" "$BL" \
'        if not _configured(route):
            continue@@@        if False:
            continue'

# 5. Настроенный рунг С полом тоже докладывается — положительный контроль наоборот:
#    проверка, докладывающая обо всех, удовлетворяет первой мутации безупречно.
mut "5. докладывается и рунг с полом (контроль)" "$BL" \
'        if store.get(floor_key):
            continue@@@        if False:
            continue'

# 6. `observe` снова говорит в лог: пол не задан, и об этом узнают, только если пойдут
#    читать.
mut "6. observe снова говорит в лог" "$BL" \
'        notify("routing", _unwatched_text(vendor, floor_key),
               dedup_extra=f"balance_unwatched:{route}")
        return@@@        return'

# 7. Рунг, у которого вовсе нет настройки пола, снова молчит в канал.
mut "7. рунг без настройки пола молчит" "$BL" \
'        notify("routing",
               f"a balance of {balance} arrived for the route {route} and this gateway "
               f"holds no balance floor setting for it at all — nobody is watching this "
               f"vendor'"'"'s credit, and the first symptom of it running out will be every "
               f"verification on that rung failing at once",
               dedup_extra=f"balance_unwatched:{route}")
        return@@@        return'

restore
echo "== восстановлено; финальный прогон"
run
