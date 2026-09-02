from __future__ import annotations

from html import escape

STYLE = """
body{font:17px -apple-system,BlinkMacSystemFont,sans-serif;max-width:640px;
margin:36px auto;padding:0 20px;line-height:1.45;color:#202124}
label{display:block;margin:20px 0 6px;font-weight:600}input{font:inherit;width:100%;
box-sizing:border-box;padding:12px;border:1px solid #bbb;border-radius:10px}
button{margin-top:24px;font:inherit;font-weight:600;padding:12px 18px;border:0;
border-radius:10px;background:#3977f6;color:white}small{color:#60646c}.notice{background:#f3f6fb;
padding:14px;border-radius:12px}.error{background:#fff0f0;color:#8b1a1a;padding:14px;border-radius:12px}
"""


def _page(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width">
<meta name="referrer" content="no-referrer">
<title>{escape(title)}</title><style>{STYLE}</style></head><body>{body}</body></html>"""


def mail_setup_html(token: str, *, error: str | None = None) -> str:
    error_html = f'<p class="error">{escape(error)}</p>' if error else ""
    return _page(
        "Студенческая почта СПбГУ",
        f"""<h1>Подключение студенческой почты</h1>{error_html}
<p class="notice"><b>Важно:</b> лучше создать отдельный пароль для внешнего приложения
в настройках VK WorkSpace. Если эта функция недоступна, сервер примет почтовый пароль,
но основной пароль ЕУЗ хранить рискованнее.</p>
<form method="post" action="/mail/setup/{escape(token)}" autocomplete="off">
<label for="address">Адрес почты СПбГУ</label>
<input id="address" name="address" type="email" required maxlength="320"
placeholder="st012345@student.spbu.ru" autocomplete="username">
<label for="app_password">Пароль для почтового подключения</label>
<input id="app_password" name="app_password" type="password" required maxlength="256"
autocomplete="off">
<small>Пароль отправляется напрямую на ваш VPS по HTTPS, проверяется через
imap.mail.ru:993 и сохраняется только в зашифрованном виде.</small><br>
<button type="submit">Подключить и проверить</button></form>
<p><small>Ссылка действует 15 минут и станет недействительной после
подключения.</small></p>""",
    )


def mail_setup_success_html(address: str) -> str:
    return _page(
        "Почта подключена",
        f"""<h1>Почта подключена ✅</h1>
<p>Новые письма для <b>{escape(address)}</b> будут приходить в Telegram.</p>
<p>Старые письма отправлены не будут. Страницу можно закрыть и вернуться в бот.</p>""",
    )
