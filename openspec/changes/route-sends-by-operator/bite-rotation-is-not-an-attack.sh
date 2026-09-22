#!/bin/bash
# Укус нормы 4.66: ротация учётных данных не выглядит атакой, а её цена названа
# числом — задача 4.60/4.66.
#
# Решение владельца 22.09.2026: потеря делается ВИДИМОЙ, а не смягчается. Прежний
# ключ не честится ни секунды, проверка подписи не ослабляется. Меняется другое: два
# отказа перестают быть одним числом, и серия подписных отказов говорит вслух, во
# что она может обойтись.
#
# Ротация действует без рестарта: сообщения, уже купленные, продолжают отчитываться
# подписью прежним ключом. Колбэк — ЕДИНСТВЕННЫЙ путь возврата, поэтому каждый такой
# возврат теряется, а учтённый расход остаётся ВЫШЕ реально потраченного — то самое
# направление, которое леджер в других местах запрещает.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_tg_callback.py tests/test_tg_gateway_adapter.py"
CB=$REPO/app/verification/tg_callback.py
TG=$REPO/app/verification/tg_gateway.py
QR=$REPO/app/db/queries.py

cd "$REPO" || exit 1
for f in "$CB" "$TG" "$QR"; do cp "$f" "$SCRATCH/$(basename "$f").orig"; done
restore() { for f in "$CB" "$TG" "$QR"; do cp "$SCRATCH/$(basename "$f").orig" "$f"; done; }
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

# 1. Дефект как найден: оба вида снова считаются под ОДНИМ ключом, и серия перекоса
#    часов неотличима от серии подделок — и от ротации, которая ни то, ни другое.
mut "1. оба вида снова под одним ключом (дефект как найден)" "$CB" \
'        rejections[refusal] += 1@@@        rejections["signature"] += 1'

# 2. Перекос часов назван подписью в самом классификаторе. Тогда ключи формально два,
#    а смысл один: всё, что не прошло, — «подпись».
mut "2. перекос часов назван подписью" "$TG" \
'        return "stale"@@@        return "signature"'

# 3. Окно проверяется ПОСЛЕ подписи. Подпись, посчитанная над воспроизведённым телом,
#    сходится безупречно, и окно — единственное, что делает повтор бесполезным;
#    проверенное после, оно называет старый колбэк «подписью» и прячет замену ключа.
mut "3. окно проверяется после подписи" "$TG" \
'    if abs(now - sent_at) > tolerance:
        return "stale"

    secret = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret, timestamp.encode() + b"\n" + body,
                        hashlib.sha256).hexdigest()
    return "" if hmac.compare_digest(expected, signature) else "signature"@@@    secret = hashlib.sha256(token.encode()).digest()
    expected = hmac.new(secret, timestamp.encode() + b"\n" + body,
                        hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return "signature"
    if abs(now - sent_at) > tolerance:
        return "stale"
    return ""'

# 4. Подписный отказ никого не будит. Тогда потеря не сделана видимой — а владелец
#    выбрал именно «сделать видимой», отказавшись смягчать.
mut "4. подписный отказ никого не будит" "$CB" \
'        if refusal == "signature":
            await _say_what_a_rotation_would_cost()@@@        if False:
            await _say_what_a_rotation_would_cost()'

# 5. Будит ВСЯКИЙ отказ, включая перекос часов, — ложная тревога, из-за которой канал
#    и глушат. Положительный контроль наоборот.
mut "5. будит и перекос часов (контроль)" "$CB" \
'        if refusal == "signature":@@@        if refusal:'

# 6. Алерт есть, но числа в нём нет: остаётся предупреждение вместо размера потери.
mut "6. алерт без числа" "$CB" \
'    in_flight = await queries.rungs_awaiting_report(TG_GATEWAY)@@@    in_flight = ""'

# 7. Счёт «в полёте» берёт и те рунги, которые уже отчитались: размер потери
#    завышается, и оператор чинит то, чего нет.
mut "7. в полёте считаются и отчитавшиеся" "$QR" \
'        "   AND (outcome IS NULL OR outcome = '"'"'carried'"'"')",@@@        "   AND (outcome IS NULL OR outcome IS NOT NULL)",'

# 8. Счёт берёт рунги БЕЗ вендорской ссылки — те, что ничего не покупали и о которых
#    нечего отчитываться.
mut "8. в полёте считаются некупленные" "$QR" \
'        " WHERE route = ? AND vendor_ref IS NOT NULL "@@@        " WHERE route = ? AND (vendor_ref IS NOT NULL OR 1=1) "'

restore
echo "== восстановлено; финальный прогон"
run
