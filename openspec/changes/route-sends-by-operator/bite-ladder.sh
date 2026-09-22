#!/bin/bash
# Укус ДРАЙВЕРА лестницы — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-ladder.sh` и `bite-carrier.sh` вместе, как на основание
# семнадцати мутаций, а обоих файлов не существовало ни в одном коммите, достижимом
# из любого рефа. Здесь девять из семнадцати — те, что про сам драйвер; остальные
# восемь в `bite-carrier.sh`.
#
# Всё, что охраняет этот файл, стоит денег: рунг, который понёс и упал, прочитанный
# как отказ, покупает тот же код у второго вендора, пока плата первого не
# возвращается до конца его `ttl`.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
# Оба файла: свойства драйвера утверждаются и там, и там, и «понёс и упал —
# лестница стоит» живёт только в носителе. Прогонять один — значит объявить
# мутацию выжившей там, где сторож есть, просто в соседнем файле.
TESTS="tests/test_ladder_walk.py tests/test_tg_gateway_carrier.py"
LD=$REPO/app/verification/ladder.py

cd "$REPO" || exit 1
cp "$LD" "$SCRATCH/ladder.py.orig"
restore() { cp "$SCRATCH/ladder.py.orig" "$LD"; }
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
  $PY - "$LD" "$expr" <<'PYEOF'
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

# 1. Гейты перечислены, но не исполняются. `checkSendAbility` оплачивается в момент
#    подтверждения, и пути возврата у этой платы своего нет.
mut "1. гейты не исполняются" \
'    for gate in gates:@@@    for gate in ():'

# 2. Отказ гейта прочитан и проигнорирован — лестница идёт дальше и тратит.
mut "2. отказ гейта проигнорирован" \
'            return Walk(refused_by=refusal)@@@            pass'

# 3. Порядок рунгов зашит в код вместо правила — и зашит ИМЕННО так, как его зашила
#    бы реализация: телеграм первым, «потому что так написано здесь». Это
#    удовлетворяет букве требования и уничтожает его смысл: правило существует, чтобы
#    менять порядок В ОТКЛЮЧЕНИЕ, без выкатки.
mut "3. телеграм первым, потому что так написано в коде" \
'    for route in rungs:@@@    for route in ([r for r in rungs if r == "tg_gateway"]
                  + [r for r in rungs if r != "tg_gateway"]):'

# 4. Молчание рунга прочитано как отказ АБОНЕНТА. Проверка, не ответившая нам, могла
#    быть подтверждена и оплачена у вендора без того, чтобы мы узнали `request_id`, —
#    плата, которую нельзя ни потратить, ни вернуть, и без счёта у неё нет имени.
mut "4. молчание = отказ абонента" \
'UNANSWERED = "unanswered"@@@UNANSWERED = "declined"'

# 5. Молчание ПОСЛЕДНЕГО рунга валит верификацию вместо того, чтобы оставить её в
#    полёте. Вендор, который нам не ответил, может доставить то, о чём не сказал, —
#    а приложению уже объявлено, что код не придёт.
#    ⚠️ Здесь НЕ мутируется значение константы `REFUSED` (или любой другой из этого
#    блока): сторож сравнивает outcome с той же константой, так что переименование
#    значения вырождается в ТОЖДЕСТВО на данных самого теста и зеленеет, ничего не
#    доказав. Мутировать надо место, которое РАЗЛИЧАЕТ, а для отказа вендора против
#    отказа абонента это карта `_OUTCOME` носителя — она в `bite-carrier.sh`.
mut "5. молчание последнего рунга валит верификацию" \
'_IN_FLIGHT = frozenset({UNANSWERED})@@@_IN_FLIGHT = frozenset()'

# 6. Граница выдаётся КАЖДОМУ рунгу заново. Медленный день у первого вендора удваивает
#    время, которое приложению обещали, и человек стоит у барьера всё это время.
mut "6. граница выдаётся каждому рунгу заново" \
'        seconds_left = deadline - time.monotonic()@@@        seconds_left = bound'

# 7. Строка рунга не говорит «в полёте». Падение между подтверждением вендора и нашей
#    записью оставляет плату, которую не к чему привязать.
mut "7. строка рунга не говорит «в полёте»" \
'                verification_id, route=route, phone=phone, outcome=ATTEMPTING)@@@                verification_id, route=route, phone=phone, outcome=CARRIED)'

# 8. Понёс и упал — лестница едет дальше. Рунг, который принял, уже оплачен, и проход
#    мимо него покупает тот же код у второго вендора, пока плата первого не
#    возвращается до конца его `ttl`.
mut "8. понёс и упал — лестница едет дальше" \
'_ADVANCING = frozenset({DECLINED, REFUSED, UNCLASSIFIED, UNANSWERED, ABSENT, INCAPABLE})@@@_ADVANCING = frozenset({DECLINED, REFUSED, UNCLASSIFIED, UNANSWERED, ABSENT, INCAPABLE, FAILED})'

# 9. Верификация названа ПЕРВЫМ пробованным рунгом, а не тем, который понёс.
#    Приложение, которому велели ждать телеграм за человека, которому Gateway отказал,
#    кладёт на экран неверную инструкцию: человек ждёт не там, пока звонит телефон
#    у него в руке.
mut "9. названа первым рунгом, а не понёсшим" \
'            outcome = await queries.set_carrying_route(verification_id, app_id, route=route)@@@            outcome = await queries.set_carrying_route(verification_id, app_id, route=rungs[0])'

restore
echo "== восстановлено; финальный прогон"
run
