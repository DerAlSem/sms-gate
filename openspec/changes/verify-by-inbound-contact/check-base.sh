#!/usr/bin/env bash
# Сторож порядка архивации для заявки verify-by-inbound-contact.
#
# Эта заявка — ДЕЛЬТА к capability `phone-verification`, которой в живой спеке
# ещё нет: её заводит соседняя открытая заявка `route-sends-by-operator`.
# Наши блоки MODIFIED и REMOVED адресуют требования, которые появятся только
# с её архивацией.
#
# `openspec validate --strict` на это молчит: он не проверяет, что
# модифицируемое требование вообще существует. Приземлимся первыми — блоки
# уедут в никуда, и содержимое пропадёт БЕЗ ЕДИНОГО СЛОВА.
#
# Выход 0 — архивировать можно. Выход 1 — нельзя, сосед ещё не приземлился.
set -uo pipefail

root=$(cd "$(dirname "$0")/../../.." && pwd)
live="$root/openspec/specs/phone-verification/spec.md"
delta="$root/openspec/changes/verify-by-inbound-contact/specs/phone-verification/spec.md"

[ -f "$delta" ] || { echo "нет дельты: $delta" >&2; exit 2; }

if [ ! -f "$live" ]; then
  echo "НЕЛЬЗЯ: живой спеки phone-verification нет — route-sends-by-operator не архивирована"
  exit 1
fi

miss=0
while IFS= read -r h; do
  grep -qxF "$h" "$live" || { echo "НЕЛЬЗЯ: в живой спеке нет требования — $h"; miss=1; }
done < <(awk '/^## (MODIFIED|REMOVED) Requirements/{f=1} /^## ADDED Requirements/{f=0} f && /^### Requirement:/{print}' "$delta")

[ "$miss" = 0 ] || exit 1
echo "можно: все модифицируемые требования есть в живой спеке"
