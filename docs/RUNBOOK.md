# دليل التشغيل (Runbook) — مُوَرِّد / Factory Finder

> الجزء الأول (عربي) هو الدليل التشغيلي السريع. الجزء الثاني "Reference (English)" هو المرجع التفصيلي الكامل (جداول المفاتيح، مفاتيح الإيقاف، الحوادث الشائعة). أسماء المتغيرات والمسارات بالإنجليزية كما هي في الكود. المستودع عام: لا أسرار هنا، القيم من البيئة فقط.

## 1. Deploy with docker compose (النشر)

1. `cp .env.example .env` ثم عبّئ القيم السرية (توليد: `python -c 'import secrets;print(secrets.token_urlsafe(48))'`).
2. الحد الأدنى للإنتاج: `FF_ENV=production`، `FF_GATEWAY_JWT_SECRET`، `FF_GATEWAY_ADMIN_TOKEN`، `FF_INTERNAL_TOKEN`، `FF_MEDIA_SIGNING_KEY`، `FF_TRUST_VERIFICATION_HASH_KEY`، `FF_SOURCING_REPORTER_HASH_KEY`، `FF_SOURCING_ANALYTICS_HASH_KEY`، `FF_PAYMENTS_PROVIDER` (غير mock) مع `FF_PAYMENTS_WEBHOOK_SECRET_<PROVIDER>` و`FF_PAYMENTS_ADMIN_TOKEN`، `FF_MEDIA_PUBLIC_BASE_URL`، `FF_GATEWAY_CORS_ORIGINS`، `FF_GATEWAY_TRUSTED_PROXIES` (خلف بروكسي).
3. PostgreSQL (موصى به): `FF_DOCKER_EXTRAS=pg` و`FF_POSTGRES_PASSWORD`، قاعدة لكل خدمة (`FF_<SVC>_DATABASE_URL=postgresql://ff:<pw>@postgres:5432/ff_<svc>`)، ثم `docker compose --profile pg up -d --build`، وبعدها لكل خدمة لها قاعدة: `docker compose run --rm <svc> alembic upgrade head`. إنشاء الجداول التلقائي مُعطّل مع Postgres (انظر `docs/DB.md`).
4. وضع تجريبي بدون Postgres: `docker compose up -d --build` (SQLite داخل الحاوية، يضيع عند إعادة الإنشاء — للتطوير فقط).
5. لوحة الإدارة (admin) تُخدَّم من البوابة على `/admin/` عند `FF_GATEWAY_SERVE_ADMIN=true`؛ لا خدمة منفصلة. تحتاج `FF_GATEWAY_ADMIN_TOKEN` (header `X-Admin-Token`). المصدر: `apps/admin`.
6. تحقق: `docker compose ps` (كلها healthy) ثم `curl -s localhost:8000/ready`.

### الخدمات والمنافذ (Ports)
المنفذ المنشور على المضيف هو 8000 (gateway) فقط. باقي الخدمات داخل الشبكة الخاصة ولا تُنشر.

| الخدمة | المنفذ الداخلي | الحالة |
|---|---|---|
| gateway | 8000 (منشور) | حالة المستخدمين، JWT، الإدارة، الوكيل لباقي الخدمات |
| sourcing | 8101 | بحث الموردين والإعلانات الأصلية |
| logistics | 8102 | الكلفة الواصلة (بدون حالة) |
| geo | 8103 | الأماكن والمسافات (بدون حالة) |
| trust | 8104 | درجة الثقة والتوثيق |
| rfq | 8105 | الطلبات والعروض والصفقات |
| messaging | 8106 | المحادثات (WebSocket عبر البوابة) |
| tracking | 8107 | تتبع الشحنات |
| notifications | 8108 | التنبيهات والدفع |
| assistant | 8109 | المساعد (بدون حالة) |
| demand | 8110 | مسودات مطابقة الطلب (إدارية فقط) |
| payments | 8111 | الفواتير والعمولة |
| media | 8112 | رفع الصور (volume `media-data`) |
| feed | 8113 | منشورات الموردين |
| freight | 8114 | سوق شركات الشحن |

(15 خدمة: gateway + 14؛ بالإضافة إلى `postgres` عند ملف `pg`.)

## 2. Health endpoints (الفحص الصحي)

- كل خدمة: `GET /health` (حياة) و`GET /ready` (جاهزية/قاعدة البيانات). البوابة: `/ready` تُظهر `upstreams {name: bool}` وحالة `degraded` إذا سقطت خدمة خلفية؛ تعيد 503 فقط إذا سقطت قاعدة البوابة.
- من الخارج: `curl -s https://<host>/health` و`/ready`. من الداخل: `docker compose exec <svc> python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:<port>/ready').read())"`.
- تتبّع الأخطاء عبر `request_id` (تُمرّر البوابة `X-Request-Id`)؛ السجلات JSON (`FF_LOG_FORMAT=text` للقراءة محلياً).

## 3. Environment variables per service (المتغيرات حسب الخدمة)

القائمة الكاملة (مع القيم الفارغة) في `.env.example`: المتغيرات الأساسية مُفعّلة، وعشرات متغيرات الضبط الدقيق (حدود، مهل، تنظيف) موجودة كتعليقات `# FF_...=` لأن القيمة الفارغة قد تُفسد حقول رقمية — فعّل السطر فقط عند الحاجة. المصدر الدقيق لكل خدمة: `services/<svc>/README.md` و`config.py`. أهم المتغيرات:

| الخدمة | متغيرات إلزامية/رئيسية |
|---|---|
| كل الخدمات | `FF_ENV`، `FF_LOG_FORMAT`، `FF_INTERNAL_TOKEN` (أو `FF_<SVC>_INTERNAL_TOKEN`) |
| gateway | `FF_GATEWAY_JWT_SECRET`، `FF_GATEWAY_ADMIN_TOKEN`، `FF_GATEWAY_DATABASE_URL`، `FF_GATEWAY_UPSTREAMS`، `FF_GATEWAY_CORS_ORIGINS`، `FF_GATEWAY_TRUSTED_PROXIES`، `FF_GATEWAY_REDIS_URL`، `FF_GATEWAY_SERVE_ADMIN`، `FF_GATEWAY_MAIL_*`/`FF_GATEWAY_SMTP_*`، `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED`، وتوكنات الإدارة التمريرية (`FF_PAYMENTS_ADMIN_TOKEN`، `FF_SOURCING_ADMIN_TOKEN`، `FF_TRUST_ADMIN_TOKEN`، `FF_FEED_ADMIN_TOKEN`، `FF_FREIGHT_ADMIN_TOKEN`، `FF_MEDIA_ADMIN_TOKEN`) |
| sourcing | `FF_SOURCING_DATABASE_URL`، `FF_SOURCING_ADAPTERS`، `FF_SOURCING_ENABLED_SOURCES`، `FF_SOURCING_KILL_SWITCH`، `FF_SOURCING_ADMIN_TOKEN`، `FF_SOURCING_TRUST_MODE`/`_BASE_URL`، مفاتيح المزودين `FF_SOURCING_ALIBABA_*`، `FF_SOURCING_ALIEXPRESS_*`، `FF_SOURCING_S1688_*`، `FF_SOURCING_MIC_*`، `FF_SOURCING_ANALYTICS_HASH_KEY`، `FF_SOURCING_REPORTER_HASH_KEY` |
| logistics | `FF_LOGISTICS_FX_PROVIDER`، `FF_LOGISTICS_FREIGHT_PROVIDER`/`_URL`/`_API_KEY`، `FF_LOGISTICS_GEO_URL`، `FF_LOGISTICS_KILL_SWITCH` |
| geo | `FF_GEO_INTERNAL_TOKEN`، `FF_GEO_DEFAULT_ROAD_FACTOR` |
| trust | `FF_TRUST_VERIFICATION_HASH_KEY` (إلزامي بالإنتاج)، `FF_TRUST_DATABASE_URL`، `FF_TRUST_ADMIN_TOKEN`، `FF_TRUST_ADAPTER`، `FF_TRUST_REVIEWS_*`، `FF_TRUST_VERIFICATION_MEDIA_HOSTS` |
| rfq | `FF_RFQ_DATABASE_URL`، `FF_RFQ_SOURCING_URL`، `FF_RFQ_COMMISSION_*`، `FF_RFQ_MIN_COMMISSION_USD` |
| messaging | `FF_MESSAGING_DATABASE_URL`، `FF_MESSAGING_REDIS_URL`، `FF_MESSAGING_ABUSE_*`، `FF_MESSAGING_MEDIA_ALLOWED_HOSTS` |
| tracking | `FF_TRACKING_DATABASE_URL`، `FF_TRACKING_PROVIDER`، `FF_TRACKING_*_BASE_URL`/`_API_KEY`، `FF_TRACKING_KILL_SWITCH`، `FF_TRACKING_NOTIFY_*`، `FF_TRACKING_REFRESH_JOB_*` |
| notifications | `FF_NOTIFICATIONS_DATABASE_URL`، `FF_NOTIFY_PUSH`/`_FCM_*`، `FF_NOTIFY_EMAIL`/`_SMTP_*`، `FF_NOTIFICATIONS_SCHEDULER_ENABLED`، `FF_NOTIFICATIONS_SOURCING_BASE_URL` |
| assistant | `FF_ASSISTANT_LLM`/`_API_KEY`/`_MODEL`/`_BASE_URL`، `FF_ASSISTANT_*_URL`، `FF_ASSISTANT_QUOTA_PER_DAY`، `FF_ASSISTANT_REDIS_URL` |
| demand | `FF_DEMAND_ENABLED` (افتراضي false)، `FF_DEMAND_DAILY_CAP`، `FF_DEMAND_DATABASE_URL`، `FF_DEMAND_PUBLISHER_ENABLED`، `FF_DEMAND_BLOCKED_*` |
| payments | `FF_PAYMENTS_PROVIDER`، `FF_PAYMENTS_DATABASE_URL`، `FF_PAYMENTS_ADMIN_TOKEN`، `FF_PAYMENTS_WEBHOOK_SECRET_*`، `FF_PAYMENTS_USDT_*`، `FF_PAYMENTS_RFQ_URL`، `FF_PAYMENTS_COMMISSION_*` |
| media | `FF_MEDIA_SIGNING_KEY` (إلزامي بالإنتاج)، `FF_MEDIA_PUBLIC_BASE_URL`، `FF_MEDIA_ADMIN_TOKEN`، `FF_MEDIA_STORAGE_BACKEND`/`_ROOT`، `FF_MEDIA_S3_*`، `FF_MEDIA_DATABASE_URL` |
| feed | `FF_FEED_DATABASE_URL`، `FF_FEED_ADMIN_TOKEN`، `FF_FEED_MEDIA_BASE_URL`، `FF_FEED_ANTISPAM_*` |
| freight | `FF_FREIGHT_DATABASE_URL`، `FF_FREIGHT_ADMIN_TOKEN`، `FF_FREIGHT_RATE_*`، `FF_FREIGHT_WEIGHT_*` |

## 4. Production guards (حراس الإنتاج — fail-closed)

مع `FF_ENV=production` ترفض الخدمة الإقلاع (`RuntimeError: FF_ENV=production requires ...`) إذا نقص سرّ لازم، بدل العمل بإعداد غير آمن:
- كل الخدمات (gateway, sourcing, logistics, trust, rfq, messaging, tracking, notifications, assistant, demand, payments, media, feed, freight) تحتاج `FF_INTERNAL_TOKEN`؛ geo بلا حارس.
- gateway: `FF_GATEWAY_JWT_SECRET` (32 حرفاً على الأقل) و`FF_GATEWAY_ADMIN_TOKEN`؛ و`FF_GATEWAY_CORS_ORIGINS` يجب ألا يحوي `*`.
- sourcing: `FF_SOURCING_REPORTER_HASH_KEY` (ليس القيمة الافتراضية العامة) و`FF_SOURCING_ANALYTICS_HASH_KEY`.
- payments: مزوّد غير `mock` (`off` أو `usdt_tron`) مع `FF_PAYMENTS_WEBHOOK_SECRET_<PROVIDER>` و`FF_PAYMENTS_ADMIN_TOKEN`.
- media: `FF_MEDIA_SIGNING_KEY`؛ trust: `FF_TRUST_VERIFICATION_HASH_KEY`.
- مع الإنتاج تُعطَّل `/docs` و`/redoc` و`/openapi.json` في كل الخدمات.
- النشر: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` (يفرض `FF_ENV=production` ويفشل قبل الإقلاع إذا نقص متغير).
عند فشل الإقلاع: اقرأ `docker compose logs <svc>`، عبّئ المتغير، ثم `docker compose up -d <svc>`.

## 5. Key rotation (تدوير المفاتيح)

التفاصيل الكاملة في الجدول بالقسم "Token and secret rotation" أدناه. الخلاصة:
- `FF_GATEWAY_JWT_SECRET`: التدوير يُبطل كل التوكنات (يعيد الجميع لتسجيل الدخول). للتدوير الناعم ضع المفتاح القديم في `FF_GATEWAY_JWT_SECRET_PREVIOUS` (للتحقق فقط) ثم احذفه بعد انتهاء مدة `FF_GATEWAY_REFRESH_TTL_SECONDS`.
- `FF_INTERNAL_TOKEN`: نفس القيمة على البوابة وكل الخدمات، وغيّرها بأمر `docker compose up -d` واحد.
- توكنات الإدارة: نفس القيمة على البوابة والخدمة المالكة؛ غير المضبوط = 404.
- `FF_TRUST_VERIFICATION_HASH_KEY`: لا تُدوَّر عادةً (الخدمة ترفض الإقلاع إذا اختلف عن مفتاح البصمات المخزنة).
- مفاتيح المزودين: أبطلها لدى المزود أولاً ثم حدّث البيئة وأعد تشغيل الخدمة الواحدة.
- أي سرّ نُشر علناً يُعتبر مسرَّباً: دوّره (حذفه من تاريخ git لا يكفي).

## 6. Postgres backups (النسخ الاحتياطي)

قاعدة لكل خدمة (gateway، sourcing، rfq، messaging، tracking، notifications، demand، payments، media، feed، freight، trust؛ logistics وgeo وassistant بلا حالة).
```
docker compose exec postgres pg_dump -U ff -Fc ff_rfq > backup/ff_rfq-$(date +%F).dump   # كرّر لكل قاعدة، يومياً على الأقل
docker run --rm -v <project>_media-data:/d -v $PWD/backup:/b alpine tar czf /b/media-$(date +%F).tgz -C /d .
```
- خزّن النسخ خارج المضيف، واحتفظ بنسخة من `FF_TRUST_VERIFICATION_HASH_KEY` و`FF_MEDIA_SIGNING_KEY` في مدير أسرار (ليس في git).
- الاستعادة خطوة بخطوة في القسم "Database restore" أدناه. جرّب استعادة تجريبية على جهاز آخر قبل الإطلاق.
- لا تعدّل revisions الـ Alembic المطبّقة (`docs/DB.md`).

## 7. Monitoring suggestions (المراقبة)

- مراقبة خارجية (uptime) على `GET /health` و`/ready` للبوابة كل دقيقة؛ تنبيه عند `degraded` أكثر من 5 دقائق أو 503.
- تنبيهات على السجلات JSON: نسبة `status>=500`، تكرار 401 على `/v1/admin`، 429 المتكررة، و`invalid_internal_token`.
- صفوف `dead` في payments outbox (تبويب Payments outbox أو `GET /v1/admin/payments/outbox?status=dead`) وفي tracking outbox.
- مساحة القرص لـ `pgdata` و`media-data`، وعمر آخر نسخة احتياطية.
- `docker compose ps` لإعادة التشغيل المتكرر (restart loop).

## 8. Incident steps (خطوات الحوادث)

### 8.1 Demand kill switch (إيقاف مطابقة الطلب)
`FF_DEMAND_ENABLED=false` (الافتراضي) ثم `docker compose up -d demand`: يعيد `approve` و`mark-published` بـ 403؛ والسقف اليومي `FF_DEMAND_DAILY_CAP` (20). أوقف أيضاً `FF_DEMAND_PUBLISHER_ENABLED`. لا تعمل بلا مراجع بشري (قاعدة 7 في CLAUDE.md). مفاتيح إيقاف أخرى (sourcing/logistics/tracking/notifications/payments/assistant) في جدول Kill switches أدناه.

### 8.2 Token revocation (إبطال التوكنات)
- مستخدم واحد: `POST /v1/auth/logout-all` (بتوكنه) يُلغي كل refresh tokens ويرفع `token_version` فتتوقف كل access tokens الصادرة (حتى الحالي). `POST /v1/auth/logout` يلغي عائلة refresh واحدة؛ إعادة استخدام refresh مستعمل تُلغي العائلة كلها. إعادة تعيين كلمة المرور ترفع `token_version` أيضاً.
- حساب مخترق بدون تعاون صاحبه: عطّل المستخدم (`is_active=false` في قاعدة البوابة، يسري خلال ~5 ثوانٍ).
- الجميع: دوّر `FF_GATEWAY_JWT_SECRET` (يُسجَّل خروج كل المستخدمين).

### 8.3 Admin-token routes (مسارات الإدارة)
كلها خلف `X-Admin-Token` = `FF_GATEWAY_ADMIN_TOKEN` على البوابة، وتعيد 404 إن لم يُضبط التوكن (على البوابة أو الخدمة): `/v1/admin/payments/outbox*`، `/v1/admin/moderation/*` (sourcing)، `/v1/admin/trust/verification/*`، `/v1/admin/freight/*`، `/v1/admin/feed/*`، `/v1/admin/media/files/{id}`، ومسارات demand والمستخدمين. تسرّب التوكن: دوّر `FF_GATEWAY_ADMIN_TOKEN` فوراً (والتوكن الفرعي المعني)، راجع السجلات لـ 401/200 على `/v1/admin`، وراجع موافقات الموردين ومسودات demand. للإيقاف الكامل: أزل `FF_GATEWAY_ADMIN_TOKEN` و`FF_GATEWAY_SERVE_ADMIN=false`.

### 8.4 خدمة متوقفة
انظر "A service is down" أدناه (ترتيب الفحص، أثر سقوط كل خدمة، إعادة الطابور).

---

# Reference (English)

# Runbook (incidents)

Audience: whoever operates the stack (docker compose). Env names below were verified against the service `config.py` files and adapters. Companion docs: `docs/DEPLOY.md`, `docs/OPS.md`, `docs/DB.md`, `docs/API_OVERVIEW.md`.

Compose env forwarding: `docker-compose.yml` forwards the operator switches from the shell / `.env` into each container with empty (or code-default) fallbacks, so leaving them unset changes nothing: `FF_ENV` (all services), the kill switches (`FF_SOURCING_KILL_SWITCH`, `FF_LOGISTICS_KILL_SWITCH`, `FF_TRACKING_KILL_SWITCH` and the per-adapter `*_DISABLED`), `FF_GATEWAY_SERVE_ADMIN`, gateway mail (`FF_GATEWAY_MAIL_*`, `FF_GATEWAY_SMTP_*`, `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED`, `FF_GATEWAY_VERIFY_URL_TEMPLATE`), `FF_SOURCING_ADAPTERS`/`_ADMIN_TOKEN`/`_ALIBABA_*`/`_LICENSED_*`, `FF_LOGISTICS_FREIGHT_*`/`FX_PROVIDER`, `FF_TRACKING_*` provider and relay vars, `FF_NOTIFY_*`, `FF_NOTIFICATIONS_SCHEDULER_ENABLED`, `FF_ASSISTANT_LLM*`/quotas, `FF_MESSAGING_ABUSE_*`, and the admin tokens (`FF_PAYMENTS_ADMIN_TOKEN`, `FF_SOURCING_ADMIN_TOKEN`, `FF_TRUST_ADMIN_TOKEN`, `FF_MEDIA_ADMIN_TOKEN`, `FF_FEED_ADMIN_TOKEN`, `FF_FREIGHT_ADMIN_TOKEN`, each forwarded to both the gateway and the owning service). Not forwarded: tuning knobs such as the gateway rate limits (`FF_GATEWAY_*_RATE_LIMIT_PER_MINUTE`, `FF_GATEWAY_TRUSTED_PROXIES`, `FF_GATEWAY_REDIS_URL`), `FF_GATEWAY_DATABASE_URL` and other minor settings: add them under that service's `environment:` (or in a `docker-compose.override.yml`). Check with `docker compose config | grep <NAME>`. `FF_NOTIFY_FCM_CREDENTIALS_FILE` is a path inside the container, so it also needs a volume mount (use `FF_NOTIFY_FCM_CREDENTIALS_JSON` instead). Feed moderation (`/v1/admin/feed/*`) and freight approval/moderation (`/v1/admin/freight/*`, the way to approve a forwarder application) go through the gateway's admin passthrough (`X-Admin-Token` = `FF_GATEWAY_ADMIN_TOKEN`, plus `FF_FEED_ADMIN_TOKEN` / `FF_FREIGHT_ADMIN_TOKEN` set on the gateway and the service; unset on either side = 404). They can still be called directly inside the private network (`docker compose exec feed ...`).

## 1. Quick triage

```
docker compose ps                                  # which container is unhealthy/restarting
docker compose logs --tail=200 <service>           # JSON lines; find "status":5xx and request_id
curl -s localhost:8000/health ; curl -s localhost:8000/ready   # /ready lists upstreams {name: bool}; "degraded" = a backend is down
```
Probes: `GET /health` (liveness) and `GET /ready` (DB reachable) exist on every service (internal ports 8101-8114, reach them with `docker compose exec <svc> python -c "import urllib.request;print(urllib.request.urlopen('http://localhost:<port>/ready').read())"`). Correlate by `request_id` (gateway forwards `X-Request-Id`). Set `FF_LOG_FORMAT=text` for readable local logs.

## 2. A service is down

1. `docker compose ps` / `docker compose logs --tail=200 <svc>`.
2. Startup refusal with `RuntimeError: FF_ENV=production requires ...`: the production guard is on and a secret is missing. All services except geo need `FF_INTERNAL_TOKEN`; media `FF_MEDIA_SIGNING_KEY`; trust `FF_TRUST_VERIFICATION_HASH_KEY`; sourcing `FF_SOURCING_REPORTER_HASH_KEY` + `FF_SOURCING_ANALYTICS_HASH_KEY`; payments a non-mock `FF_PAYMENTS_PROVIDER` + its `FF_PAYMENTS_WEBHOOK_SECRET_<PROVIDER>` + `FF_PAYMENTS_ADMIN_TOKEN`; the gateway `FF_GATEWAY_JWT_SECRET` (>=32 chars), `FF_GATEWAY_ADMIN_TOKEN` and non-`*` `FF_GATEWAY_CORS_ORIGINS`. Fix the env, then restart.
3. `docker compose restart <svc>`; if the image is stale: `docker compose up -d --build <svc>`.
4. Effects of each service being down (the gateway keeps running; `/ready` shows `degraded`): sourcing -> search/listings fail (assistant and notifications depend on it); logistics -> quotes fail; geo -> logistics cannot resolve places; trust -> sourcing falls back (trust mode `http` has a 0.8 s timeout); rfq -> requests/offers/deals; payments -> invoices (settlement events wait in the payments outbox and retry); tracking -> shipments (tracking outbox to notifications retries with backoff, then marks rows dead after `FF_TRACKING_NOTIFY_MAX_ATTEMPTS` = 8); media -> image uploads/reads (and private verification files); feed -> posts/follows/comments only; freight -> forwarder quotes/requests only; demand -> admin drafts only (never user-facing); assistant -> the chat assistant only; trust verification routes and the admin console's document review fail if trust is down.
5. Gateway down: nothing is reachable to clients. Check its DB (`FF_GATEWAY_DATABASE_URL`, SQLite by default; `/ready` is 503 only when the gateway DB is down) and that `FF_GATEWAY_UPSTREAMS` JSON is valid.
6. Dead payment events: admin console "Payments outbox" tab, or `GET /v1/admin/payments/outbox?status=dead` and `POST /v1/admin/payments/outbox/{id}/requeue` (header `X-Admin-Token`; needs `FF_PAYMENTS_ADMIN_TOKEN` set on the gateway too, same value as on payments, otherwise 404).

## 3. Database restore

Databases: one per service. gateway (users, default SQLite), sourcing (native listings, price history, analytics), rfq, messaging, tracking, notifications, demand, payments, media (metadata; image files live on the `media-data` volume), feed, freight, trust (verification documents, append-only audit, reports, score snapshots; also back up `FF_TRUST_VERIFICATION_HASH_KEY`). logistics, geo, assistant are stateless.

Backup (Postgres profile `pg`, user `ff`):
```
docker compose exec postgres pg_dump -U ff -Fc ff_rfq > backup/ff_rfq-$(date +%F).dump     # repeat per database
docker run --rm -v <project>_media-data:/d -v $PWD/backup:/b alpine tar czf /b/media-$(date +%F).tgz -C /d .
```
Restore (one database):
```
docker compose stop gateway <svc>
docker compose exec -T postgres psql -U ff -c "DROP DATABASE IF EXISTS ff_rfq" -c "CREATE DATABASE ff_rfq"
docker compose exec -T postgres pg_restore -U ff -d ff_rfq --no-owner < backup/ff_rfq-YYYY-MM-DD.dump
docker compose run --rm <svc> alembic upgrade head     # bring the schema to the current revision
docker compose up -d <svc> gateway
```
SQLite default (dev only): the DB file is inside the container (`/app/...`) and is lost on recreate; copy it out with `docker compose cp <svc>:/app/<file>.db backup/` before any rebuild. Move the gateway DB (`FF_GATEWAY_DATABASE_URL`) and the others to Postgres or a mounted volume before real users. After any restore, test: login, open a request, `GET /ready`. Never edit applied Alembic revisions (see `docs/DB.md`). Nothing in the repo verifies a restore for you: do a trial restore on a spare machine before launch.

## 4. Token and secret rotation

All values live only in the environment / `.env` (never in git; the repo is public). Generate: `python -c 'import secrets;print(secrets.token_urlsafe(48))'`. After changing, recreate the affected containers: `docker compose up -d <svc>`.

| Secret | Env | Effect of rotating |
|---|---|---|
| User JWT signing key | `FF_GATEWAY_JWT_SECRET` | All access and refresh tokens become invalid; every user must log in again. If unset, an ephemeral key is generated and tokens die on every restart. |
| Admin token | `FF_GATEWAY_ADMIN_TOKEN` | Admin console and `/v1/admin/*` need the new value; unset = those routes answer 404. If leaked: rotate at once, then review supplier-claim approvals and demand drafts. |
| Internal service token | `FF_INTERNAL_TOKEN` | Must be identical on the gateway and every service; rotate them all in one `docker compose up -d`. During a partial rollout calls fail with 401 `invalid_internal_token`. |
| Payments admin token | `FF_PAYMENTS_ADMIN_TOKEN` | Set the same value on payments and on the gateway. |
| Payments webhook secrets | `FF_PAYMENTS_WEBHOOK_SECRET_MOCK`, `FF_PAYMENTS_WEBHOOK_SECRET_USDT_TRON` | Update the sender (HMAC `X-FF-Signature`, 300 s tolerance) at the same time; unset = webhooks answer 503. |
| Sourcing moderation admin token | `FF_SOURCING_ADMIN_TOKEN` | Set on sourcing and (same value) on the gateway; unset = `/v1/admin/moderation/*` answers 404. |
| Trust / freight / feed / media admin tokens | `FF_TRUST_ADMIN_TOKEN`, `FF_FREIGHT_ADMIN_TOKEN`, `FF_FEED_ADMIN_TOKEN`, `FF_MEDIA_ADMIN_TOKEN` | Same pattern: set the same value on the service and on the gateway; unset on either side = `/v1/admin/trust/verification/*`, `/v1/admin/freight/*`, `/v1/admin/feed/*`, `/v1/admin/media/files/*` answer 404. |
| Media signing key | `FF_MEDIA_SIGNING_KEY` | Signs 5-minute private file URLs; rotating only invalidates links already issued. Required with `FF_ENV=production`. |
| Verification hash key | `FF_TRUST_VERIFICATION_HASH_KEY` | Keys document-number fingerprints. Do NOT rotate casually: the service refuses to start if it differs from the key the stored fingerprints used. Required with `FF_ENV=production`. |
| Provider keys | `FF_SOURCING_ALIBABA_APP_KEY`, `FF_SOURCING_ALIBABA_APP_SECRET`, `FF_SOURCING_ALIBABA_ACCESS_TOKEN`, `FF_LOGISTICS_FREIGHT_API_KEY`, `FF_TRACKING_CONTAINER_API_KEY`, `FF_TRACKING_AWB_API_KEY`, `FF_TRACKING_VESSEL_API_KEY`, `FF_NOTIFY_SMTP_PASSWORD`, `FF_GATEWAY_SMTP_PASSWORD`, `FF_NOTIFY_FCM_CREDENTIALS_JSON`/`_FILE`, `FF_MEDIA_S3_ACCESS_KEY_ID`/`_SECRET_ACCESS_KEY`, `FF_ASSISTANT_LLM_API_KEY`, `FF_PAYMENTS_USDT_EXPLORER_API_KEY` | Revoke at the provider first if leaked, create a new one, update env, restart the one service. |
| Postgres password | `FF_POSTGRES_PASSWORD` + each `FF_<SVC>_DATABASE_URL` | `ALTER USER ff PASSWORD '...'` inside Postgres, then update every URL and restart the services. |

If any secret was ever committed or pasted publicly: treat it as leaked and rotate it; removing it from git history is not enough.
Per-user: disabling a user (`is_active`) takes effect on the next proxied request after at most ~5 s. `POST /v1/auth/logout` revokes a refresh-token family; replaying a used refresh token revokes the whole family.

## 5. Kill switches (exact names found in code)

Truthy values for the `*_KILL_SWITCH` / `*_DISABLED` flags: the code accepts `1`, `true`, `yes`, `on` (case-insensitive); use `1`. They are read at call time from the process environment, so set them in the shell / `.env` (compose forwards them, see the note at the top) and recreate the container (`docker compose up -d <svc>`).

| Goal | Switch | Service | Behaviour |
|---|---|---|---|
| Stop all real supplier-data adapters | `FF_SOURCING_KILL_SWITCH=1` | sourcing | Real adapters disabled; mock/native results continue, `sources[].warning` is set. |
| Stop only the Alibaba Open Platform adapter | `FF_SOURCING_ALIBABA_OPENAPI_DISABLED=1` | sourcing | Same, one adapter. |
| Turn real adapters off by config | unset/empty `FF_SOURCING_ADAPTERS` (default) and keep `FF_SOURCING_ENABLED_SOURCES=mock,native` | sourcing | Only mock + native listings are queried. |
| Stop all live freight rates | `FF_LOGISTICS_KILL_SWITCH=1` | logistics | Built-in tables are used. |
| Stop only the HTTP freight provider | `FF_LOGISTICS_FREIGHT_DISABLED=1` (or `FF_LOGISTICS_FREIGHT_PROVIDER=mock`) | logistics | Built-in tables. |
| Live FX off | `FF_LOGISTICS_FX_PROVIDER=mock` (values: `mock`, `ecb`) | logistics | Deterministic mock rates. |
| Stop all real tracking providers | `FF_TRACKING_KILL_SWITCH=1` | tracking | Responses carry a `warning` (e.g. `provider_unavailable:kill_switch`); mock fallback when `FF_TRACKING_FALLBACK_TO_MOCK` is true (default). |
| Per tracking provider | `FF_TRACKING_CONTAINER_DISABLED=1`, `FF_TRACKING_AWB_DISABLED=1`, `FF_TRACKING_VESSEL_DISABLED=1`, `FF_TRACKING_HTTP_DISABLED=1` | tracking | One provider off. Also `FF_TRACKING_PROVIDER=mock` (default). |
| Stop background tracking refresh | `FF_TRACKING_REFRESH_JOB_ENABLED=false` (default) | tracking | No scheduled provider calls. |
| Stop tracking -> notifications relay | `FF_TRACKING_NOTIFY_RELAY=off` (default; `on` enables) | tracking | Shipment alerts not forwarded. |
| Stop push notifications | `FF_NOTIFY_PUSH=off` (values: `off`, `mock`, `fcm`) | notifications | No device pushes. |
| Stop email digests | `FF_NOTIFY_EMAIL=off` (values: `off`, `mock`, `smtp`) | notifications | No digest mail. |
| Stop scheduled alert evaluation | `FF_NOTIFICATIONS_SCHEDULER_ENABLED=false` (default) | notifications | Alerts evaluated only when triggered internally. |
| Stop verification/other gateway mail | `FF_GATEWAY_MAIL_BACKEND=off` (values: `off`, `mock`, `smtp`) | gateway | No mail; if `FF_GATEWAY_REQUIRE_EMAIL_VERIFIED=true` is on, users who are not verified stay blocked from payments/claims/listings, so switch that off too. |
| Stop all payments | `FF_PAYMENTS_PROVIDER=off` (values: `mock`, `usdt_tron`, `off`) | payments | Invoice creation returns 503. Webhooks need their secrets, unset = 503. |
| Demand matching (public-reply drafting) | `FF_DEMAND_ENABLED=false` (default) | demand | Global kill switch: `approve` and `mark-published` return 403. Daily approvals capped by `FF_DEMAND_DAILY_CAP` (default 20). Keep OFF without a human reviewer. |
| Assistant LLM | `FF_ASSISTANT_LLM=off` (values: `off`, `mock`, `anthropic`); `FF_ASSISTANT_LLM_REWRITE=false` | assistant | Rule-based parsing only; no external LLM calls. Per-day quotas: `FF_ASSISTANT_QUOTA_PER_DAY` (200), `FF_ASSISTANT_ANON_QUOTA_PER_DAY` (30). |
| Admin console / admin API off | unset `FF_GATEWAY_ADMIN_TOKEN` (routes answer 404); `FF_GATEWAY_SERVE_ADMIN=false` (default) hides the `/admin/` static console | gateway | |
| Chat abuse filter | `FF_MESSAGING_ABUSE_FILTER_ENABLED` (default true), action `FF_MESSAGING_ABUSE_ACTION` | messaging | Flags/blocks messages matching the term list. |
| Hide one bad listing | admin console Moderation tab, or `POST /v1/admin/moderation/listings/{id}/hide` | sourcing via gateway | Reversible with `.../restore`. |
| Block a user | set `is_active` false on the user (effect within ~5 s) | gateway | No self-service endpoint; do it in the gateway DB. |

Production guard (not a kill switch, but a safety net): `FF_ENV=production` makes services refuse to start without their tokens (section 2).

## 5b. Retention (what is deleted automatically)
Defaults and the exact scope are in `docs/OPS.md` (Retention and limits). Short version: demand signals and rejected drafts 90 days (after each poll); notifications alerts 180 days and deliveries 30 days (only while `FF_NOTIFICATIONS_SCHEDULER_ENABLED=true`); payments webhook-replay rows 180 days, delivered outbox events 180 days, attempts of expired/failed invoices 365 days (in `POST /v1/payments/sweep`; invoices, ledger and pending/dead outbox events are never deleted); sourcing price history and analytics 400 days; trust reports 365 days (rejected/stale pending only) and score snapshots 730 days. To keep data longer, raise the matching `*_RETENTION_DAYS`; `0` disables the rule for demand and payments.

## 6. Common incidents

- **Users suddenly logged out everywhere**: gateway restarted without `FF_GATEWAY_JWT_SECRET` (ephemeral key) or the secret was rotated. Set a fixed secret.
- **429 Too Many Requests for many users**: behind a proxy without `FF_GATEWAY_TRUSTED_PROXIES`, all clients share one IP. Set it to the proxy CIDRs. Limits: `FF_GATEWAY_RATE_LIMIT_PER_MINUTE` (300), `FF_GATEWAY_AUTH_RATE_LIMIT_PER_MINUTE` (30), `FF_GATEWAY_USER_WRITE_RATE_LIMIT_PER_MINUTE` (120), `FF_GATEWAY_MEDIA_RATE_LIMIT_PER_MINUTE` (3000). Multiple replicas need `FF_GATEWAY_REDIS_URL`.
- **Search returns only demo data**: expected. Real adapters are off until `FF_SOURCING_ADAPTERS` lists one and credentials are set (and they are unverified against live APIs).
- **Prices look stale/odd**: freight/duty tables are approximations unless a freight provider is configured; FX is mock unless `FF_LOGISTICS_FX_PROVIDER=ecb`.
- **Images missing after redeploy**: the `media-data` volume was not mounted/persisted or `FF_MEDIA_PUBLIC_BASE_URL` points to the wrong origin.
- **Suspected admin-token guessing**: the gateway throttles failed `/v1/admin` attempts per IP; rotate `FF_GATEWAY_ADMIN_TOKEN` anyway and check logs for 401s on `/v1/admin`.
- **Payment received but deal not marked paid**: look at the payments outbox for `pending`/`dead` events and requeue (section 2, step 6); check `docker compose logs rfq`.
- **Security finding follow-up**: open items are tracked in `docs/fixes/*.md` (blocks a phase until fixed).

## Container hardening notes (infra)

- Every service starts with `uvicorn ... --no-server-header --timeout-keep-alive 5 --no-proxy-headers` (Dockerfile.service, via `exec` so SIGTERM is graceful). `--no-proxy-headers` is deliberate: the gateway resolves `X-Forwarded-For` itself (`FF_GATEWAY_TRUSTED_PROXIES`); internal services only see the gateway.
- Networks: `internal` (`internal: true`, no outbound internet) holds all services and postgres; only the gateway publishes a port. `egress` is attached to the gateway and to services whose real adapters call external APIs (sourcing, logistics, tracking, notifications, assistant, payments). A service not listed there cannot reach the internet; add `networks: [internal, egress]` if a new adapter needs it. Postgres is never published.
- Healthchecks use a 2 s timeout; json-file logs rotate at 10 MB x 3 (postgres included); postgres runs with all capabilities dropped except those its entrypoint needs.
- Not done (needs a runtime test with Docker): `read_only: true` for services that default to SQLite in `/app` (dev mode); ship a reverse proxy/TLS in front of the gateway and bind `8000` to loopback there; pin base image digests (see `docs/fixes/supply-chain-review-2026-10.md`).
