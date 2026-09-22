#!/usr/bin/env python3
"""Укус сторожей вокруг САМОГО КОДА — задача 4.60.

🔴 Этот файл заведён 22.09.2026 и заведён поздно. Спека ссылалась на `bite-code.py`
в ЧЕТЫРЁХ местах как на основание четырёх требований — 19 мутаций суммарно, — а
файла не существовало ни в одном коммите, достижимом из любого рефа. Это тот же
урок, что и с `bite-limits.sh`: **ссылка на укус — утверждение о коде, и проверяется
она так же, как всякое другое.**

Скрипт на Python, а не на bash, потому что мутаций девятнадцать и якоря у них
многострочные: таблица читается, цепочка одинарных кавычек — нет.

Цена ошибки здесь не деньги, а сам секрет: код, доживший до ответа двери, до лога
или до чужого приложения, — это верификация, которую может закрыть кто угодно.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PY = REPO.parent.parent.parent / "venv" / "bin" / "python"
TESTS = "tests/test_the_code_and_who_may_spend_it.py"

QR = REPO / "app" / "db" / "queries.py"
RT = REPO / "app" / "api" / "router.py"
SC = REPO / "app" / "api" / "schemas.py"
FILES = [QR, RT, SC]

# (заголовок, файл, якорь, замена). Якорь обязан встретиться РОВНО один раз.
MUTATIONS: list[tuple[str, Path, str, str]] = [

    # --- 4.7 и 4.11: код выбирает шлюз, и два живых кода различны ---------------------
    ("1. предложенный приложением код принят", SC,
     "        if v is not None:",
     "        if False:"),
    ("2. код чеканится не спросив, что живо (дефект, замеренный 21.09)", RT,
     "    code = _new_code(await queries.open_codes_for(body.phone))",
     "    code = _new_code(set())"),
    ("3. занятое множество прочитано и не учтено", RT,
     '        if code != "0000" and code not in taken:',
     '        if code != "0000":'),
    ("4. живой код ЧУЖОГО номера считается занятым (контроль)", QR,
     '        "WHERE phone = ? AND status = \'pending\' AND expires_at > CURRENT_TIMESTAMP "',
     '        "WHERE (phone = ? OR 1=1) AND status = \'pending\' '
     'AND expires_at > CURRENT_TIMESTAMP "'),

    # --- 4.10: условия, которые обнулённый код иначе прячет ---------------------------
    # Две из трёх держались вторым фильтром ниже — поэтому сторожа кладут код ОБРАТНО
    # в терминальную строку прежде, чем предъявить его.
    ("5. подтверждение не спрашивает, открыта ли верификация", QR,
     "        \" WHERE id = ? AND app_id = ? AND status = 'pending' \"\n"
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\",",
     "        \" WHERE id = ? AND app_id = ? \"\n"
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\","),
    ("6. подтверждение не спрашивает про потолок попыток", QR,
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\",",
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND ? IS NOT NULL AND code = ?\","),
    ("7. подтверждение не спрашивает про срок", QR,
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\",\n"
     "        (verification_id, app_id, limit, code),",
     "        \"   AND attempts < ? AND code = ?\",\n"
     "        (verification_id, app_id, limit, code),"),
    ("8. подтверждает ЛЮБОЙ код", QR,
     "       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = 'check', code = NULL \"\n"
     "        \" WHERE id = ? AND app_id = ? AND status = 'pending' \"\n"
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\",",
     "       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = 'check', code = NULL \"\n"
     "        \" WHERE id = ? AND app_id = ? AND status = 'pending' \"\n"
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND ? IS NOT NULL\","),
    ("9. неверный код не стоит попытки", QR,
     '        "UPDATE verifications SET attempts = attempts + 1 "',
     '        "UPDATE verifications SET attempts = attempts "'),
    ("10. «вышло и время, и попытки» названо попытками, а не сроком", QR,
     "    if await _is_past_its_deadline(verification_id):\n"
     '        return "expired"\n'
     '    return "no_attempts_left"',
     "    if not await _is_past_its_deadline(verification_id):\n"
     '        return "expired"\n'
     '    return "no_attempts_left"'),

    # --- 4.20: токен одного приложения не ходит по верификациям другого ----------------
    ("11. чтение верификации не ограничено владельцем", QR,
     '        "SELECT * FROM verifications WHERE id = ? AND app_id = ?",',
     '        "SELECT * FROM verifications WHERE id = ? AND (app_id = ? OR 1=1)",'),
    ("12. подтверждение не ограничено владельцем", QR,
     "        \" WHERE id = ? AND app_id = ? AND status = 'pending' \"\n"
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\",",
     "        \" WHERE id = ? AND (app_id = ? OR 1=1) AND status = 'pending' \"\n"
     "        \"   AND expires_at > CURRENT_TIMESTAMP AND attempts < ? AND code = ?\","),

    # --- 4.22: кода нет нигде, кроме матчера ------------------------------------------
    ("13. подтверждённая верификация хранит код дальше", QR,
     "        \"UPDATE verifications SET status = 'confirmed', \"\n"
     "        \"       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = 'check', "
     "code = NULL \"",
     "        \"UPDATE verifications SET status = 'confirmed', \"\n"
     "        \"       confirmed_at = CURRENT_TIMESTAMP, confirmed_by = 'check' \""),
    ("14. исчерпавшая попытки хранит код дальше", QR,
     "        \"UPDATE verifications SET status = 'failed', reason = 'no_attempts_left', \"\n"
     "            \"       code = NULL \"",
     "        \"UPDATE verifications SET status = 'failed', reason = 'no_attempts_left' \""),
    ("15. проваленная рунгом хранит код дальше", QR,
     "        \"UPDATE verifications SET status = 'failed', reason = ?, code = NULL \"",
     "        \"UPDATE verifications SET status = 'failed', reason = ? \""),
    ("16. истёкшая хранит код дальше", QR,
     "        f\"UPDATE verifications SET status = 'expired', reason = 'expired', "
     "code = NULL \"",
     "        f\"UPDATE verifications SET status = 'expired', reason = 'expired' \""),
    ("17. причина провала выносит код наружу", QR,
     "    reason = _without_the_code(reason, await _code_of(verification_id))\n"
     "    cursor = await db.execute(",
     "    cursor = await db.execute("),
    ("18. слова вендора на рунге выносят код наружу", QR,
     "    reason = _without_the_code(reason, await _code_behind_rung(rung_id))",
     "    pass"),
    ("19. причина, записанная при создании рунга, выносит код наружу", QR,
     "    reason = _without_the_code(reason, await _code_of(verification_id))\n"
     "    async with db.execute(",
     "    async with db.execute("),
]


def run() -> str:
    for cache in REPO.rglob("__pycache__"):
        if ".git" not in cache.parts:
            shutil.rmtree(cache, ignore_errors=True)
    out = subprocess.run([str(PY), "-m", "pytest", TESTS, "-p", "no:cacheprovider", "-q"],
                         cwd=REPO, capture_output=True, text=True)
    return (out.stdout.strip().splitlines() or ["<нет вывода>"])[-1]


def main() -> int:
    scratch = Path(tempfile.mkdtemp())
    originals = {f: f.read_text(encoding="utf-8") for f in FILES}

    def restore() -> None:
        for f, text in originals.items():
            f.write_text(text, encoding="utf-8")

    try:
        print("== 0. ИСХОДНОЕ обязано быть зелёным")
        print("  ", run())

        survivors = []
        for name, path, old, new in MUTATIONS:
            restore()
            text = originals[path]
            hits = text.count(old)
            if hits != 1:
                print(f"!! {name}: якорь встретился {hits} раз — мутация НЕ ПРОГНАНА")
                survivors.append(name)
                continue
            path.write_text(text.replace(old, new, 1), encoding="utf-8")
            line = run()
            print(f"== {name}\n   {line}")
            if "failed" not in line:
                survivors.append(name)

        restore()
        print("== восстановлено; финальный прогон")
        print("  ", run())
        if survivors:
            print("\n🔴 ВЫЖИВШИЕ — дыра или негодная мутация, разбирать поимённо:")
            for s in survivors:
                print("   -", s)
            return 1
        print(f"\nвсе {len(MUTATIONS)} мутаций красные")
        return 0
    finally:
        restore()
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
