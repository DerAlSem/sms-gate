#!/bin/bash
# Укус нормы 4.64: собственный номер шлюза нормализуется — или отказывается —
# в МОМЕНТ СОХРАНЕНИЯ.
#
# Находка круга критики 22.09.2026. `RouteOffer.number` заведён ровно затем, чтобы
# потребитель собрал `tel:` не читая нашей английской прозы, — значит номер,
# сохранённый как набран, кладёт наш ввод данных на ЧУЖОЙ экран. Отказ немой:
# абонент набирает пустоту, окно закрывается, верификация отчитывается `expired` и
# неотличима от человека, который просто не позвонил.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_gateways_own_number_is_normalised_when_saved.py"
SS=$REPO/app/settings_store.py
RT=$REPO/app/verification/routes.py

cd "$REPO" || exit 1
for f in "$SS" "$RT"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$SS" "$RT"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Дефект как найден: тип свободная строка, проверки нет вовсе.
mut "1. тип снова свободная строка (дефект как найден)" "$SS" \
'    Spec("gateway_msisdn", "msisdn", "", "Verification", False,@@@    Spec("gateway_msisdn", "str", "", "Verification", False,'

# 2. Проверка есть, НОРМАЛИЗАЦИИ нет: сохранённое отдаётся как набрано. Ровно та
#    форма доказательства, которую эта заявка уже находила бесполезной — «валидатор
#    виден в коде» не охраняет ФОРМУ хранимого.
mut "2. проверяем, но не переписываем" "$SS" \
'        try:
            return validate_and_normalize(raw, store.phone_region)
        except ValueError:
            return raw                          # validate_raw reports it@@@        return raw'

# 3. Переписываем, но не проверяем: не-номер доезжает до хранилища.
mut "3. переписываем, но не отказываем" "$SS" \
'        from app.phone import validate_and_normalize
        validate_and_normalize(raw, store.phone_region)
        return@@@        return'

# 4. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: пустое тоже отказано. Валидатор, отказывающий всему,
#    удовлетворяет мутации 3 безупречно — и делает ненастроенный эстейт
#    несохраняемым.
mut "4. пустое тоже отказано (контроль)" "$SS" \
'        if raw.strip() == "":
            return
        from app.phone import validate_and_normalize@@@        from app.phone import validate_and_normalize'

# 5. 🔴 Проверка перенесена НА ИСПОЛЬЗОВАНИЕ вместо сохранения — соблазнительная
#    альтернатива, которую норма отвергает явным доводом. Мутация из двух правок,
#    поэтому идёт мимо `mut`.
#    ⚠️ Ожидание было «дверной тест позеленеет, красны останутся только настройки».
#    ОНО НЕВЕРНО, и это и есть находка: поле нормализуется, а ПРЕДЛОЖЕНИЕ рядом с
#    ним собирается из того же сырого значения и остаётся национальным. Получается
#    ровно то, что норма запрещает отдельным абзацем: «поле, расходящееся с
#    предложением, хуже отсутствия поля, потому что приложение поверит данным».
#    То есть чинить на использовании нельзя не только по времени отказа — чинить
#    там СОГЛАСОВАННО не выходит вовсе, пока источник один и он ненормализован.
restore
$PY - "$SS" <<'PYEOF'
import sys
path = sys.argv[1]
s = open(path, encoding='utf-8').read()
old = '    Spec("gateway_msisdn", "msisdn", "", "Verification", False,'
new = '    Spec("gateway_msisdn", "str", "", "Verification", False,'
assert s.count(old) == 1
open(path, 'w', encoding='utf-8').write(s.replace(old, new, 1))
PYEOF
$PY - "$RT" <<'PYEOF'
import sys
path = sys.argv[1]
s = open(path, encoding='utf-8').read()
old = "        return self._gateway_number or None"
new = """        from app.phone import validate_and_normalize
        from app.settings_store import store as _store
        try:
            return validate_and_normalize(self._gateway_number, _store.phone_region)
        except ValueError:
            return self._gateway_number or None"""
assert s.count(old) == 1
open(path, 'w', encoding='utf-8').write(s.replace(old, new, 1))
PYEOF
echo "== 5. проверка перенесена на использование (дверь чинит, сохранение — нет)"
run

restore
echo "== восстановлено; финальный прогон"
run
