#!/bin/bash
# Укус задачи 6.6: перепись писателей `messages.status` считает ЗАПИСИ СТАТУСА,
# а не имена функций.
#
# Находка свипа 22.09.2026. Требование говорит «every code path that writes
# messages.status», а сторож сверял `set(KNOWN_STATUS_WRITERS)` — только ИМЕНА. Второй
# `UPDATE ... SET status = 'rejected'` ВНУТРИ уже зарегистрированной функции проходил
# насквозь: перепись зелёная, объявленный статус не читает никто.
#
# 🔴 Это тот же урок, что 4.60 и 6.1 в этой же заявке: ЕДИНИЦА СЧЁТА СТОРОЖА ОБЯЗАНА
# СОВПАДАТЬ С ЕДИНИЦЕЙ НОРМЫ. Норма считает переходы, сторож считал функции — и был
# зелен на нарушении, выглядя исправным.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_delivery_hooks.py"
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
cp "$QR" "$SCRATCH/queries.py.orig"
restore() { cp "$SCRATCH/queries.py.orig" "$QR"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ "$REPO"/tests/__pycache__ \
         2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$QR" "$expr" <<'PYEOF'
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

# 1. 🔴 Дефект как найден: ВТОРОЙ переход внутри уже зарегистрированного писателя.
#    Новое имя не появилось — значит именная перепись этого не видит по построению.
mut "1. второй статус внутри известного писателя (дефект как найден)" \
'        "UPDATE messages SET status = '\''delivered'\'', delivered_at = CURRENT_TIMESTAMP WHERE id = ?",
        (message_id,),
    )
    await db.commit()@@@        "UPDATE messages SET status = '\''delivered'\'', delivered_at = CURRENT_TIMESTAMP WHERE id = ?",
        (message_id,),
    )
    await db.execute(
        "UPDATE messages SET status = '\''rejected'\'' WHERE id = ?", (message_id,),
    )
    await db.commit()'

# 2. Статус, записываемый известным писателем, ПОДМЕНЁН. Имя на месте, переход другой —
#    приложение услышит «доставлено» о сообщении, отмеченном иначе.
mut "2. известный писатель пишет другой статус" \
'        UPDATE messages
        SET status = '\''expired'\''@@@        UPDATE messages
        SET status = '\''rejected'\'''

# 3. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: НОВЫЙ писатель отдельной функцией. Эту форму именная
#    перепись ловила и обязана ловить дальше — без неё правка выше выглядела бы как
#    «перепись вообще ничего не проверяет».
mut "3. новый писатель отдельной функцией (контроль)" \
'async def set_message_delivered(message_id: int) -> None:@@@async def set_message_rejected(message_id: int) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE messages SET status = '\''rejected'\'' WHERE id = ?", (message_id,),
    )
    await db.commit()


async def set_message_delivered(message_id: int) -> None:'

restore
echo "== восстановлено; финальный прогон"
run
