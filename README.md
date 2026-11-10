# UniPrint

UniPrint — проект учёта заявок, принтеров, физических картриджей и их движения. Текущий код — ранний backend MVP; он ещё не готов к использованию с реальными пользователями или университетской инфраструктурой.

## Локальная разработка

Требуется Python 3.14 и `uv`.

```sh
uv sync --dev
UNIPRINT_DATABASE_URL=sqlite:///./uniprint-dev.db uv run alembic upgrade head
UNIPRINT_AUTH_MODE=development UNIPRINT_DATABASE_URL=sqlite:///./uniprint-dev.db uv run uniprint-dev-user --id dev-operator --name 'Local operator' --department 'Dev department'
UNIPRINT_AUTH_MODE=development UNIPRINT_DATABASE_URL=sqlite:///./uniprint-dev.db uv run uvicorn uniprint.api:app --reload
```

В другом терминале запустите интерфейс:

```sh
npm run dev
```

Откройте локальный адрес Vite и в переключателе dev-идентичности укажите `dev-operator`. Для проверки разных сценариев можно выбрать роли `employee`, `approver`, `technician`, `storekeeper`, `admin`.

В development-режиме API принимает `X-Dev-User-Id` и `X-Dev-Roles`, но только с loopback-соединения; пользователь должен существовать в таблице `users`. Это временный адаптер: он не проверяет пароль и не предназначен для сетевого или производственного использования. Вне `UNIPRINT_AUTH_MODE=development` доменные методы закрыты ответом 503 до подключения утверждённого IdP. Роли в локальной разработке передаются заголовком, маршруты согласования пока фиксированы в коде.

Проверки:

```sh
uv run pytest
```

`tests/test_postgres_concurrency.py` проверяет параллельную выдачу и установку на PostgreSQL. Эти тесты пропускаются без `UNIPRINT_TEST_DATABASE_URL`; для запуска укажите отдельную одноразовую базу PostgreSQL на loopback с именем `uniprint_test`:

```sh
UNIPRINT_TEST_DATABASE_URL='postgresql+psycopg://uniprint_test:<password>@127.0.0.1:5432/uniprint_test' uv run pytest -q tests/test_postgres_concurrency.py
```

Тесты удаляют схему только в этой базе и заново накатывают миграции. Не указывайте рабочую или университетскую БД.

Миграции `0001_initial`–`0003_label_tokens` добавлены в репозиторий. Команда `alembic upgrade head` меняет указанную БД; запускайте её только на локальной базе разработки. Не направляйте её на реальную или университетскую БД без отдельного разрешения.

## Текущие API-маршруты

- `GET /health`
- `GET/POST /api/cartridge-models`
- `POST /api/printer-models`, `GET/POST /api/printers`
- `GET /api/cartridges`, `POST /api/cartridges` — приём экземпляра на склад с обязательным `Idempotency-Key`
- `GET /api/cartridges/{asset_code}/events` — журнал движений картриджа для кладовщика, техника или администратора
- `GET /api/cartridges/{asset_code}/label.svg` — SVG QR-этикетка для кладовщика или администратора; QR кодирует случайный токен, в SVG напечатаны код и модель картриджа
- `GET/POST /api/requests`, `GET /api/requests/{id}`, `GET /api/requests/{id}/events`
- `POST /api/requests/{id}/transitions`
- `POST /api/requests/{id}/issue` — выдача совместимого складского экземпляра после согласования, с `Idempotency-Key`
- `POST /api/requests/{id}/install`, `/remove` — подтверждение установки/снятия, с ручными показаниями счётчика и `Idempotency-Key`
- `GET /api/installations` — текущие установки для ролей `storekeeper`, `technician`, `admin`
- `POST /api/requests/{id}/return` — возврат со склада/на заправку/в ремонт с ручным показанием счётчика
- `POST /api/cartridges/{asset_code}/refill-completion`, `/repair-completion` и `/inspection` — завершение сервиса и контрольная проверка

Frontend содержит быстрые формы выдачи/установки/снятия/возврата, складской приёмки, завершения заправки и ремонта с контрольной проверкой, реестр активных установок, загрузку QR-этикеток и журнал движений картриджей. Журнал и установки доступны ролям `storekeeper`, `technician` и `admin`. Передача реальных принтерных данных, автоматическое согласование, формальный процесс списания, отчёты, LDAP/AD и SNMP/IPP-коннекторы ещё не реализованы. Frontend доступен через Vite при разработке и собирается внутрь `src/uniprint/static` командой `npm run build` для локального запуска FastAPI.

`npm run build` проверяет типы и создаёт статические файлы для FastAPI. В production-сборке переключатель dev-идентичности отсутствует, а API остаётся закрытым до настройки утверждённого IdP.
