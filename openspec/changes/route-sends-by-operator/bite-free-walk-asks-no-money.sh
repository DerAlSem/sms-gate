#!/bin/bash
# Укус: ходка, все рунги которой бесплатны, не спрашивается про деньги.
#
# Задача 4.61. Находка круга критики 22.09.2026 — единственная, до которой оба
# воркера дошли НЕЗАВИСИМО, и потому она пошла первой.
#
# До правки `placement.place` отдавал `gates.for_paid_ladder` КАЖДОЙ ходке, а
# `PLACED_HERE` включает `sms_out`. Три гейта из четырёх — про деньги. На
# штатных настройках это не угол, а обычный путь: `may_spend` отгружается нулём
# всем приложениям, а штатное правило шлёт каждого неназванного оператора на
# ["sms_out"] в одиночку. В день выката верификация для абонента МТС получала
# 422 «не имеет права тратить на платный маршрут», не потратив ничего и не имея
# чего тратить.
#
# Набор был на этом ЗЕЛЁН: дверной тест включает `may_spend` на весь файл, а
# модемный до двери не доходит — зовёт `carriers_for` и `walk` напрямую, то есть
# по единственному пути, где связка гейтов подаётся руками.
#
# 🔴 Мутация 2 — та, ради которой сторож имеет право на существование: решение
# по ПЕРВОМУ рунгу вместо оставшихся. Правило вправе назвать бесплатный рунг
# впереди платного; такая ходка читается как бесплатная и доходит до вендора без
# права, без потолка и без лимита на номер. Все соседние сторожа при этом
# зелены. Без такой мутации сторож был бы пересказом соседнего.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_a_free_walk_is_not_asked_about_money.py"
GT=$REPO/app/verification/gates.py
PL=$REPO/app/verification/placement.py

cd "$REPO" || exit 1
for f in "$GT" "$PL"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$GT" "$PL"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Сам дефект: связка собирается безусловно, как было до 22.09.
mut "1. деньги спрашиваются у всякой ходки (исходный дефект)" "$GT" \
'    if not any(r in routes.PAID_ROUTES for r in rungs):
        return (blacklist_gate(phone),)@@@    if False:
        return (blacklist_gate(phone),)'

# 2. 🔴 Решение по ПЕРВОМУ рунгу. Ловит ТОЛЬКО этот сторож.
mut "2. решение по первому рунгу, а не по оставшимся" "$GT" \
'    if not any(r in routes.PAID_ROUTES for r in rungs):@@@    if not (rungs and rungs[0] in routes.PAID_ROUTES):'

# 3. Обратный перегиб: деньги не спрашиваются НИКОГДА.
mut "3. деньги не спрашиваются никогда" "$GT" \
'    if not any(r in routes.PAID_ROUTES for r in rungs):@@@    if True:'

# 4. Чёрный список теряется на бесплатной ветке — гейт 4.58 вырождается.
mut "4. чёрный список выпал из бесплатной ветки" "$GT" \
'        return (blacklist_gate(phone),)@@@        return ()'

# 5. Лестница читается дважды: связка собирается по СВОЕЙ ходке.
#    Здесь подаётся платная жёстко — связка перестаёт зависеть от ходки вовсе.
mut "5. связка собрана не по рунгам этой ходки" "$PL" \
'        gates=gates.for_paid_ladder(app_id, phone, rungs),@@@        gates=gates.for_paid_ladder(app_id, phone, [route]) if route else gates.for_paid_ladder(app_id, phone, rungs),'

echo
echo "== восстановление и контроль: снова обязано быть зелёным"
restore
run
