#!/bin/bash
# Укус НОСИТЕЛЯ телеграм-рунга — задача 4.60.
#
# 🔴 Спека ссылалась на `bite-carrier.sh` вместе с `bite-ladder.sh` как на основание
# семнадцати мутаций, и обоих файлов не существовало ни в одном коммите, достижимом
# из любого рефа. Здесь восемь из семнадцати — те, что про носителя; девять про сам
# драйвер лежат в `bite-ladder.sh`.
#
# Адаптер ниже знает провод, носитель знает ДЕНЬГИ. Подтверждённая проверка
# возможности — это уже понесённая плата, у которой нет своего пути возврата:
# вендорский возврат привязан к `ttl`, а `ttl` начинается только с отправкой.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
# Оба файла по той же причине, что и в `bite-ladder.sh`: свойства носителя
# утверждаются по обе стороны границы.
TESTS="tests/test_tg_gateway_carrier.py tests/test_ladder_walk.py"
CR=$REPO/app/verification/tg_carrier.py

cd "$REPO" || exit 1
cp "$CR" "$SCRATCH/tg_carrier.py.orig"
restore() { cp "$SCRATCH/tg_carrier.py.orig" "$CR"; }
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
  $PY - "$CR" "$expr" <<'PYEOF'
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

# 1. Рунг куплен для верификации, которой осталось жить меньше вендорского пола.
#    Раздуть `ttl` до тридцати секунд — значит отдать вендору сообщение, переживающее
#    верификацию, к которой оно относится, и к тому же самому `ttl` привязан
#    автоматический возврат.
mut "1. рунг куплен ниже вендорского пола" \
'        if ttl < tg_gateway.TTL_MIN:@@@        if False:'

# 2. Отказ по короткой жизни зачтён АБОНЕНТУ. Рунг, который выглядит отказывающим
#    каждому, вынут из правила по неверной причине.
mut "2. отказ по короткой жизни зачтён абоненту" \
'                outcome=ladder.INCAPABLE,@@@                outcome=ladder.DECLINED,'

# 3. Плата не записана до отправки. Падение между подтверждением вендора и нашей
#    записью оставляет плату, не принадлежащую ничему, и единственный симптом —
#    дрейфующий баланс.
mut "3. плата не записана до отправки" \
'        await queries.set_rung_outcome(
            rung_id, outcome=ladder.ATTEMPTING, vendor_ref=ability.request_id, cost=cost,
            reason="the ability check confirmed and was charged")@@@        pass'

# 4. `ttl` вендору — константа вместо остатка жизни верификации. Сообщение переживает
#    верификацию, а возврат привязан к тому же числу.
mut "4. ttl вендору — константа" \
'            phone, code=code, ttl=ttl, token=token, request_id=ability.request_id,@@@            phone, code=code, ttl=300, token=token, request_id=ability.request_id,'

# 5. Провал отправки ПОСЛЕ платы двигает лестницу. Тот же код покупается у второго
#    вендора, пока плата первого не возвращается до конца его `ttl`.
mut "5. провал после платы двигает лестницу" \
'            return ladder.Attempt(outcome=ladder.FAILED, vendor_ref=ability.request_id,
                                  cost=cost, reason=sent.error)@@@            return ladder.Attempt(outcome=ladder.DECLINED, vendor_ref=ability.request_id,
                                  cost=cost, reason=sent.error)'

# 6. Отказ ВЕНДОРА схлопнут в отказ абонента КАРТОЙ — то есть в том самом месте,
#    которое их различает. Мутировать значение константы `ladder.REFUSED` было бы
#    тождеством на данных теста: сторож сравнивает с той же константой.
mut "6. карта исходов схлопывает отказ вендора в decline" \
'    tg_gateway.REFUSED: ladder.REFUSED,@@@    tg_gateway.REFUSED: ladder.DECLINED,'

# 7. Отказ вендора и неразмещаемый отказ проходят молча. С двумя платными рунгами
#    «вендор без денег» — это вопрос, на который оператор обязан ответить прежде, чем
#    действовать, и разница между двухминутным пополнением и отключением.
mut "7. отказ вендора молча" \
'        if ability.kind in _LOUD:@@@        if False:'

# 8. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: носитель не несёт никогда. Без него весь файл
#    удовлетворяется реализацией, которая просто ничего не покупает.
mut "8. носитель не несёт никогда (контроль)" \
'        if ability.kind != tg_gateway.ABLE:@@@        if True:'

restore
echo "== восстановлено; финальный прогон"
run
