#!/bin/bash
# Укус: номер нормализуется ДО того, как читается оператор.
#
# Норма спорит не про опрятность, а про маршрут: таблица операторов ключуется
# нормализованным номером, ненормализованный резолвится в «оператора нет», берёт
# запись правила для неизвестного — и для абонента МегаФона это модем, то есть
# ровно тот маршрут, от которого вся заявка уводит. Запрос при этом успешен.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_the_call_rung_is_reachable.py"
SC=$REPO/app/api/schemas.py
PH=$REPO/app/phone.py

cd "$REPO" || exit 1
for f in "$SC" "$PH"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$SC" "$PH"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Валидатор у двери верификаций снят — номер едет как написан. Это и есть
#    состояние, в котором норма стояла необоснованной: валидатор был виден в
#    коде, и «виден в коде» сторожем не является.
mut "1. валидатор снят с двери верификаций" "$SC" \
'    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_and_normalize(v, store.phone_region)

    @field_validator("code")@@@    @field_validator("code")'

# 2. Валидатор на месте, но ПРОПУСКАЕТ строку как есть — форма нормы, в которой
#    он выродился в проверку существования, а не в приведение.
mut "2. валидатор ничего не приводит" "$SC" \
'    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return validate_and_normalize(v, store.phone_region)

    @field_validator("code")@@@    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        validate_and_normalize(v, store.phone_region)
        return v

    @field_validator("code")'

# 3. Приведение сломано у источника: национальная форма даёт другой номер, а не
#    отказ. Кусает и отправку, и верификацию — на то он и общий источник.
mut "3. приведение ломается у источника" "$PH" \
'    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)@@@    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.NATIONAL)'

restore
echo "== восстановлено; финальный прогон"
run
