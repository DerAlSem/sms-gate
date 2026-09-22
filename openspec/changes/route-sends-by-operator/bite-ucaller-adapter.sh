#!/bin/bash
# Укус сторожей адаптера uCaller (4.17). Мутация ломает охраняемое — сторож обязан покраснеть.
#
# Скрэтчпад берётся mktemp'ом, а не прописан строкой: прежний bite-ucaller.sh носил путь
# сессии, которой давно нет, и на чужой машине `cp` молча падал бы — а вместе с ним и
# restore, оставляя мутацию в рабочем дереве.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_ucaller_adapter.py tests/test_ucaller_credentials.py"
UC=$REPO/app/verification/ucaller.py
RT=$REPO/app/api/router.py

cd "$REPO" || exit 1
cp "$UC" "$SCRATCH/ucaller.py.orig"
cp "$RT" "$SCRATCH/router.py.orig"
trap 'cp "$SCRATCH/ucaller.py.orig" "$UC"; cp "$SCRATCH/router.py.orig" "$RT"; rm -rf "$SCRATCH"' EXIT

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/api/__pycache__ \
         "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

restore() { cp "$SCRATCH/ucaller.py.orig" "$UC"; cp "$SCRATCH/router.py.orig" "$RT"; }

echo "== 0. ИСХОДНОЕ обязано быть зелёным"
run

mut() { # name file python-expr
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

# 1. Различать конверты по `status`, а не по наличию `error` — то самое чтение по референсу.
mut "1. конверт по status, а не по error" "$UC" \
'    error = envelope.get("error")
    if error:@@@    error = envelope.get("error")
    if not envelope.get("status"):'

# 2. `status: false` прочитан как «ничего не создано» — авторизация выброшена.
mut "2. status:false = ничего не создано" "$UC" \
'    return Call(kind=ACCEPTED, placed=parse_placed(payload))@@@    if not payload.get("status"):
        return Call(kind=DECLINED)
    return Call(kind=ACCEPTED, placed=parse_placed(payload))'

# 3. Отказ опознан по наличию числового `code` — правдоподобное чтение референса, и оно
#    объявляет отказом успешную авторизацию, у которой под тем же ключом лежит наш код.
mut "3. отказ опознан по наличию code" "$UC" \
'    error = envelope.get("error")
    if error:@@@    error = envelope.get("error")
    if "code" in envelope:'

# 4. `repeat_times` обязателен — падение на штатном истечении окна.
mut "4. repeat_times с умолчанием вместо None" "$UC" \
'        repeat_times=_as_int(body.get("repeat_times")),@@@        repeat_times=_as_int(body.get("repeat_times")) or 0,'

# 5. `balance` отдан как есть — пол сработает на одну верификацию позже.
mut "5. balance_after без вычета cost" "$UC" \
'        if self.balance_before is None or self.cost is None:
            return None
        return self.balance_before - self.cost@@@        return self.balance_before'

# 6. Диапазон кода сужен до \d{4} — 0000 уезжает вендору.
mut "6. код \\d{4} без исключения 0000" "$UC" \
'    if not _CODE.match(code or "") or code == "0000":@@@    if not _CODE.match(code or ""):'

# 7. Дверь снова чеканит 0000.
mut "7. дверь чеканит 0000" "$RT" \
'        if code != "0000" and code not in taken:@@@        if code not in taken:'

# 8. Ключ идемпотентности рисуется заново — ретрай не дедуплицируется.
mut "8. ключ рисуется, а не выводится" "$UC" \
'    digest = bytearray(hashlib.sha256(_KEY_NAMESPACE + str(rung_id).encode()).digest()[:16])@@@    digest = bytearray(uuid.uuid4().bytes)'

# 9. Неизвестный код ошибки прочитан как отказ абоненту.
mut "9. неизвестная ошибка = decline" "$UC" \
'    return UNCLASSIFIED


def resolved@@@    return DECLINED


def resolved'

# 10. Отсутствующий call_status прочитан как разрешённый исход.
mut "10. отсутствующий call_status = решено" "$UC" \
'    return info is not None and info.call_status in (NOT_CONNECTED, PLACED)@@@    return info is not None and info.call_status != PENDING'

# 11. Номер уезжает вендору с плюсом.
mut "11. номер с плюсом" "$UC" \
'    return re.sub(r"\D", "", phone)


def validate_code@@@    return "+" + re.sub(r"\D", "", phone)


def validate_code'

# 12. Не-JSON тело прочитано как отказ вендора, а не как «ответа не было».
mut "12. не-JSON тело = отказ" "$UC" \
'        raise _Unreadable(f"{method}: HTTP {response.status_code}, non-JSON body") from e@@@        return True, {}, "non-JSON", None'

# 13. initRepeat снова вызываем — метод, который спека запрещает звать.
mut "13. initRepeat снова разрешён" "$UC" \
'VENDOR_METHODS = frozenset({"initCall", "getInfo", "getBalance", "getService"})@@@VENDOR_METHODS = frozenset({"initCall", "getInfo", "getBalance", "getService", "initRepeat"})'

# 14. Код уезжает в лог вместе с телом запроса.
mut "14. тело запроса в логе" "$UC" \
'        logger.info("ucaller: initCall refused (%s, code %s)", error, error_code)@@@        logger.info("ucaller: initCall refused (%s, code %s) for %s", error, error_code, body)'

restore
echo "== восстановлено; финальный прогон"
run
