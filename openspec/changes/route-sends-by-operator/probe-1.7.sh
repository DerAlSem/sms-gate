#!/bin/bash
# Замер 1.7 — достижим ли ЧУЖОЙ абонент в Telegram, и почём.
#
# Одноразовый харнесс заявки route-sends-by-operator. Снимает то, чего нет ни в
# одном сэмпле 18.09: баланс тогда был нулевой, и checkSendAbility не вызывался
# ни разу. Всё, что он пишет в captures/, становится wire-контрактом адаптера.
#
# 🔴 Деньги. checkSendAbility ПЛАТЕН при подтверждении. Бесплатен ровно отказ —
# и ещё один sendVerificationMessage с тем же request_id. Поэтому режимы
# разделены: подтверждение печатается и ждёт второй команды, чтобы плата не
# сгорела и чтобы код не уехал живому человеку раньше, чем его увидели вы.
#
# Токен в переписку не попадает: читается из TG_TOKEN, который вы экспортируете
# в своей ssh-сессии.
#
#   export TG_TOKEN=...
#   bash probe-1.7.sh check 79851600019
#   bash probe-1.7.sh send 79851600019 <request_id> 1234
#   bash probe-1.7.sh status <request_id>
#   bash probe-1.7.sh revoke <request_id>
#
set -u

API=https://gatewayapi.telegram.org
OUT=${OUT:-./captures-1.7}
mkdir -p "$OUT"

if [ -z "${TG_TOKEN:-}" ]; then
  echo "НЕТ ТОКЕНА: export TG_TOKEN=... сначала"
  exit 2
fi

# Одна мера времени на вызов. Вопрос «укладывается ли вендор в терпение
# лестницы» решается этим числом, а не рассуждением: сегодня проба рунга стоит
# на доводе «этот рунг умирает громко», и довод обязан стать замером.
call() {
  local method="$1" body="$2" name="$3"
  local t0 t1 ms
  # Арифметика самим шеллом: `bc` на derserver НЕ стоит (проверено
  # 20.09.2026), и вызов через него дал бы пустое время при успешном запросе —
  # то есть замер молча потерялся бы именно там, где он нужен.
  t0=$(date +%s%N)
  curl -sS -m 30 -X POST "$API/$method" \
    -H "Authorization: Bearer $TG_TOKEN" \
    -H "Content-Type: application/json" \
    -d "$body" -o "$OUT/$name.json" -w '%{http_code}' > "$OUT/$name.code"
  t1=$(date +%s%N)
  ms=$(( (t1 - t0) / 1000000 ))
  echo "$method: HTTP $(cat "$OUT/$name.code") за ${ms} мс"
  echo "--- $OUT/$name.json ---"
  cat "$OUT/$name.json"
  echo
}

case "${1:-}" in
  check)
    # Номер уходит в E.164 с плюсом. Вернётся он БЕЗ плюса — так было во всех
    # семи сэмплах, и адаптер на это уже рассчитан.
    n="${2:?номер без плюса, например 79851600019}"
    call checkSendAbility "{\"phone_number\":\"+$n\"}" "check-$n"
    echo
    echo "ok:false  -> отказ. БЕСПЛАТНО. Это и есть написание отказа,"
    echo "             ради которого DECLINE_ERRORS стоит пустым."
    echo "ok:true   -> подтверждение. ПЛАТА УЖЕ СПИСАНА. Возьмите request_id"
    echo "             из result и запустите send — иначе плата сгорит."
    ;;
  send)
    n="${2:?номер}"; rid="${3:?request_id из check}"; code="${4:?4-8 цифр}"
    # ttl 300 — остаток жизни проверки по норме спеки, и внутри вендорских
    # 30..3600. code_length не шлём никогда: код наш, вендорский мы сверить
    # не сможем.
    call sendVerificationMessage \
      "{\"phone_number\":\"+$n\",\"request_id\":\"$rid\",\"code\":\"$code\",\"ttl\":300,\"payload\":\"probe 1.7\"}" \
      "send-$n"
    ;;
  status)
    rid="${2:?request_id}"
    # В адаптере этот вызов сознательно не используется — счётчик попыток наш.
    # Здесь он инструмент замера, а не часть продукта.
    call checkVerificationStatus "{\"request_id\":\"$rid\"}" "status-$rid"
    ;;
  revoke)
    rid="${2:?request_id}"
    echo "Напоминание: 18.09 отзыв ответил true ДВАЖДЫ и оба раза ничего не убрал."
    echo "Здесь проверяется ровно одно: ведёт ли себя ПЛАТНОЕ сообщение третьему"
    echo "лицу иначе. Сразу после — status, и смотрим, стал ли он revoked."
    call revokeVerificationMessage "{\"request_id\":\"$rid\"}" "revoke-$rid"
    ;;
  *)
    echo "режимы: check <номер> | send <номер> <request_id> <код> | status <request_id> | revoke <request_id>"
    exit 1
    ;;
esac
