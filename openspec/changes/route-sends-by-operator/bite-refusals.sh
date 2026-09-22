#!/bin/bash
# Укус СЧЁТА того, что стоит правило маршрутизации, — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-refusals.sh` как на основание тринадцати мутаций, а
# файла не существовало ни в одном коммите, достижимом из любого рефа.
#
# Правило, поставленное во время отключения, переживёт отключение: МегаФон снова
# принимает трафик, запись всё ещё на месте, приложения всё ещё отказаны, и ни на
# одном экране об этом не сказано. Счёт — это разница между правилом, которое
# пересматривают, и правилом, о котором забыли.
#
# ⚠️ Счёт не значит «производится»: единственный вызывающий сегодня — `ladder.walk`.
# Отказ на пути отправки, дающий замеренные семьдесят в месяц, — задача 4.6.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_route_refusals.py"
RF=$REPO/app/verification/refusals.py

cd "$REPO" || exit 1
cp "$RF" "$SCRATCH/refusals.py.orig"
restore() { cp "$SCRATCH/refusals.py.orig" "$RF"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/db/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() {
  local name="$1" expr="$2"
  restore
  $PY - "$RF" "$expr" <<'PYEOF'
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

# 1. Счёт не пишется в базу вовсе.
mut "1. отказ не считается" \
'    await db.execute(
        "INSERT INTO route_refusals (operator_key, operator, app_id, route) "@@@    await db.execute(
        "SELECT ? IS NOT NULL, ? IS NOT NULL, ? IS NOT NULL, ? IS NOT NULL "
        "-- INSERT INTO route_refusals (operator_key, operator, app_id, route) "'

# 2. 🔴 Группировка не по СВЁРНУТОМУ имени. Счёт, расколотый между двумя написаниями,
#    делает правило вдвое дешевле, чем оно есть, — и это ровно то направление ошибки,
#    которое здесь опасно. Замер 08.09.2026: `upper()` недосчитал половину.
mut "2. группировка не по свёрнутому имени" \
'    key = rule.fold(name)@@@    key = name'

# 3. Приложение не записано: «семьдесят отказов» не отвечает, звонить ли разработчику
#    одного приложения или снимать правило.
mut "3. приложение не записано" \
'        (key, name, app_id, route),@@@        (key, name, "?", route),'

# 4. Маршрут, который не смог понести, не записан.
mut "4. маршрут не записан" \
'        (key, name, app_id, route),@@@        (key, name, app_id, "?"),'

# 5. Неразрешённый оператор не считается под написанием правила, а проваливается в
#    пустоту — то есть в общий итог, из которого его не достать.
mut "5. неразрешённый оператор не назван" \
'    name = (operator or "").strip() or rule.UNKNOWN@@@    name = (operator or "").strip()'

# 6. 🔴 Алерт повешен на `send_error`. Этот тумблер на стоковой установке ВЫКЛЮЧЕН, а
#    всякая установка с этим дефектом — стоковая.
mut "6. алерт повешен на send_error" \
'    notify("routing",
           f"{app_id} was refused for {name}@@@    notify("send_error",
           f"{app_id} was refused for {name}'

# 7. Дедупликация по ЭЛЕМЕНТУ вместо оператора и маршрута. Семьдесят в месяц и
#    больше — один алерт на отказанное сообщение учит оператора не читать канал,
#    который несёт и «вендор без денег».
mut "7. дедупликация по элементу" \
'           dedup_extra=f"refused:{key}:{route}")@@@           dedup_extra=f"refused:{key}:{route}:{id(name)}")'

# 8. Дедупликация по ОДНОМУ оператору — обратная ошибка: один отказывающий оператор
#    глушит алерт про следующего.
mut "8. дедупликация по одному оператору" \
'           dedup_extra=f"refused:{key}:{route}")@@@           dedup_extra="refused")'

# 9. Запись, чьи маршруты изменились, НЕ начинает период пересмотра заново — решение
#    пересмотрели, а часы идут со старого конца.
mut "9. изменённая запись не начинает период заново" \
'        elif stored[key] != as_stored:@@@        elif False:'

# 10. Запись, выпавшая из правила, остаётся под наблюдением: оператору напоминают о
#     правиле, которого больше нет.
mut "10. выпавшая запись остаётся под наблюдением" \
'            await db.execute(
                "DELETE FROM route_rule_entries WHERE operator_key = ?", (key,))@@@            pass'

# 11. Период пересмотра — число в коде вместо настройки.
mut "11. период пересмотра зашит в код" \
'    days = store.operator_route_review_days@@@    days = 30'

# 12. Отчёт идёт КАЖДЫЙ тик, а не раз в период: `reviewed_at` не проставляется.
mut "12. отчёт каждый тик" \
'        await db.execute(
            "UPDATE route_rule_entries SET reviewed_at = CURRENT_TIMESTAMP "
            " WHERE operator_key = ?", (entry["operator_key"],))@@@        pass'

# 13. `*` и `?` попадают в отчёт. Они не называют оператора — это базовая линия
#     шлюза, — и правило, держащее только их, не отвело никуда: ежемесячный отчёт о
#     нём учит игнорировать канал, который несёт и записи, которые отвели.
mut "13. базовая линия попадает в отчёт" \
'        " WHERE operator_key NOT IN (?, ?) "@@@        " WHERE (operator_key NOT IN (?, ?) OR 1=1) "'

restore
echo "== восстановлено; финальный прогон"
run
