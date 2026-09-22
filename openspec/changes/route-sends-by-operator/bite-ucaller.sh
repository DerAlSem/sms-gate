#!/bin/bash
# Укус сторожей записи uCaller. Мутация ломает охраняемое — сторож обязан покраснеть.
set -u
REPO=$(cd "$(dirname "$0")/../../.." && pwd)
# mktemp, а не путь сессии: прежний здесь носил скрэтчпад сессии, которой уже нет, и
# `cp` в несуществующий каталог молча уносил с собой restore — мутация оставалась в дереве.
SCRATCH=$(mktemp -d)
PY=$REPO/../../../venv/bin/python
TESTS="tests/test_ucaller_credentials.py tests/test_vendor_credentials.py"
UC=$REPO/app/verification/ucaller.py
SS=$REPO/app/settings_store.py

cd "$REPO" || exit 1
cp "$UC" "$SCRATCH/ucaller.py.orig"
cp "$SS" "$SCRATCH/settings_store.py.orig"

run() {
  rm -rf "$REPO"/app/__pycache__ "$REPO"/app/verification/__pycache__ "$REPO"/tests/__pycache__ 2>/dev/null
  $PY -m pytest $TESTS -p no:cacheprovider -q 2>&1 | tail -1
}

restore() { cp "$SCRATCH/ucaller.py.orig" "$UC"; cp "$SCRATCH/settings_store.py.orig" "$SS"; }
trap 'restore; rm -rf "$SCRATCH"' EXIT

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

mut "1. дот исчез из бирера" "$UC" 'return f"{left}.{right}"@@@return f"{left}{right}"'
mut "2. половины перепутаны" "$UC" 'return f"{left}.{right}"@@@return f"{right}.{left}"'
mut "3. не хватает одной половины — сойдёт" "$UC" 'if not left or not right:@@@if not left and not right:'
mut "4. пасту не чистим" "$UC" 'left = (key or "").strip()@@@left = (key or "")'
mut "5. configured_bearer читает только ключ" "$UC" 'return bearer(store.ucaller_key, store.ucaller_service_id)@@@return bearer(store.ucaller_key, store.ucaller_key)'
mut "6. ключ объявлен не секретным" "$SS" 'Spec("ucaller_key", "str", "", "Verification", True,@@@Spec("ucaller_key", "str", "", "Verification", False,'
mut "7. запись приезжает с значением" "$SS" 'Spec("ucaller_service_id", "str", "", "Verification", False,@@@Spec("ucaller_service_id", "str", "1692", "Verification", False,'
mut "8. вторая половина не объявлена" "$SS" '    Spec("ucaller_service_id", "str", "", "Verification", False,
         "uCaller service id, the second half of the credential above "
         "(blank = the flash_call rung is never offered)"),
@@@'

restore
echo "== ВОССТАНОВЛЕНО, обязано быть зелёным"
run
