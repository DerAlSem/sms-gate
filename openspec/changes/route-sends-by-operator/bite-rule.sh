#!/bin/bash
# Укус САМОГО ПРАВИЛА маршрутизации — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-rule.sh` как на основание восьми мутаций, а файла не
# существовало ни в одном коммите, достижимом из любого рефа.
#
# Правило — данные, а не ветвь, и капабилити существует потому, что операторы
# отзывают модемный маршрут в масштабе всего эстейта: замена обязана быть достижима
# НАСТРОЙКОЙ во время отключения, а не выкаткой в него.
#
# Самая дорогая из восьми — первая. `number_operators` держит МегаФон под двумя
# написаниями (`МЕГАФОН` у 120 номеров и `МегаФон` у 57, прочитано 08.09.2026):
# сравнение по `==` увело бы треть абонентов верно, а остальных — на маршрут, который
# их отвергает, молча.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_routing_rule.py"
RL=$REPO/app/verification/rule.py

cd "$REPO" || exit 1
cp "$RL" "$SCRATCH/rule.py.orig"
restore() { cp "$SCRATCH/rule.py.orig" "$RL"; }
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
  $PY - "$RL" "$expr" <<'PYEOF'
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

# 1. 🔴 Сравнение имён точной строкой вместо свёртки. Треть абонентов МегаФона
#    уезжает верно, остальные — на маршрут, который их отвергает.
mut "1. точное сравнение имён вместо свёртки" \
'    return unicodedata.normalize("NFKC", name or "").strip().casefold()@@@    return name or ""'

# 2. Порядок лестницы зашит в код. Какой платный путь пробуется первым — денежное
#    решение, которое ездит с ценами вендоров и достижимостью.
mut "2. порядок лестницы зашит в код" \
'    if key and key in rule:
        return list(rule[key])@@@    if key and key in rule:
        return sorted(rule[key], key=lambda r: r != "tg_gateway")'

# 3. Неизвестный маршрут принят при сохранении. Обнаружится он при отправке — то есть
#    человеком, стоящим у барьера, а на платных рунгах человеком у барьера ПОСЛЕ
#    того, как деньги ушли.
mut "3. неизвестный маршрут принят" \
'        if route not in _ALLOWED:@@@        if False:'

# 4. 🔴 Сломанное правило прочитано как ПУСТОЕ. Пустым оно отправляет весь трафик
#    отведённого оператора обратно на маршрут, который его отвергает, и без строчки в
#    логе — единственный отказ этой капабилити, который и тотален, и нем.
mut "4. сломанное правило прочитано как пустое" \
'        raise UnreadableRule(f"the stored routing rule is not JSON: {exc}") from exc@@@        return {}'

# 5. Правило, которому нечего ответить, УГАДЫВАЕТ модем. Умолчание, к которому
#    пришли по недосмотру, и есть тот самый тихий failover.
mut "5. нечего ответить — угадываем модем" \
'    return [REFUSE]


def refuses@@@    return ["sms_out"]


def refuses'

# 6. `app_id` принят в правиле. Это то же самое зашивание, переехавшее в настройку:
#    маршрут решался бы тем, КТО спрашивает, а не тем, что достижимо.
mut "6. app_id принят в правиле" \
'    if "app_id" in item:@@@    if False:'

# 7. Два написания одного оператора приняты при сохранении. Кто из двух победит,
#    решил бы порядок списка — невидимо.
mut "7. два написания одного оператора приняты" \
'        if key in seen:@@@        if False:'

# 8. `refuse`, продолжающийся в лестницу. Лестница, идущая дальше отказа, отказом не
#    является.
mut "8. refuse продолжается в лестницу" \
'    if REFUSE in routes and len(routes) > 1:@@@    if False:'

restore
echo "== восстановлено; финальный прогон"
run
