# GameNet Pro — ماتریس نیازمندی‌ها در برابر مستر اسپک (§۰ تا §۲۱۱)

- تاریخ بررسی: 2026-09-23
- کامیت مبنا: `02634a0` (P3-2) + تغییرات ثبت‌نشده P3-3 (inventory، در حال انجام)
- تست‌ها: 147 سبز (`pytest tests/`)
- وضعیت‌ها: `DONE` = پیاده + تست | `PARTIAL` = ناقص | `MISSING` = نشده | `CONFLICT` = تعمداً متفاوت (توضیح داده شده) | `DEFERRED` = فاز آینده طبق نقشه

> نکته نگاشت فازها: شماره‌فازهای TODO ریپو با §۲۰۴ اسپک یکی نیست. پوشش واقعی بر اساس §۲۰۴ در جدول اول آمده است.

## ۱) پوشش فازهای §۲۰۴

| فاز §۲۰۴ | پوشش | وضعیت |
|---|---|---|
| PHASE 0 — Repository Audit | GAP-ANALYSIS + این ماتریس | DONE |
| PHASE 1 — Architecture + Database Foundation | لایه‌بندی، ۱۲ مایگریشن، WAL/FK، ایندکس‌ها | DONE (به‌جز بکاپ قبل از مایگریت) |
| PHASE 2 — Customer + Credit + Payment | مشتری/PIN، اعتبار/VIP/پکیج/بالانس، فروش/پرداخت/ریفاند، قیمت‌گذاری، تخفیف | DONE (به‌جز لاگین مشتری، Debt، کد خطا) |
| PHASE 3 — Session + PC + Server | سشن/انتقال/تایم‌لاین، PC، حضور، lease، heartbeat، WS، ایجنت headless | DONE (به‌جز Extend سشن، RECOVERING، تمایز اینترنت/LAN) |
| PHASE 4 — Client Agent | ایجنت headless: auth/heartbeat/فرمان/ACK/بکاف/ریکاوری | DONE (بدون UI؛ بدون WS-client، بدون jitter) |
| PHASE 5 — Kiosk + Lockdown | فقط primitive قفل ویندوز + بوت قفل‌شده | MISSING (عمده) |
| PHASE 6 — Game Catalog + Launcher + Process Monitor | هیچ‌چیز | MISSING (کامل) |
| PHASE 7 — Recovery + Resilience | startup checks، safe-mode، reconciliation، pause-on-disconnect، reconnect | DONE (به‌جز grace period، رویدادهای امنیتی، دیسک‌فول) |
| PHASE 8 — Inventory + Cash + Shift + Reservation | شیفت/صندوق/ریفاند DONE؛ موجودی در حال انجام؛ رزرو/صف/گروه MISSING | PARTIAL |
| PHASE 9 — Reports + Alerts + Dashboard | فقط audit-list/verify و presence خام | MISSING (عمده) |
| PHASE 10 — Installer + Build | هیچ‌چیز | MISSING (کامل) |
| PHASE 11 — Failure Testing | ~۱۸ از ۳۰ سناریوی §۱۷۲ (جزئیات پایین) | PARTIAL |
| PHASE 12 — Hardening | lockout، audit-chain، idempotency؛ لاگ/بکاپ/ریت‌لیمیت ناقص | PARTIAL |

## ۲) ماتریس تفصیلی (§ به §)

### اصول و معماری (§۰–§۳، §۱۲۷–§۱۲۸، §۱۶۲–§۱۶۴، §۲۰۰، §۲۰۲، §۲۱۱)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 0–1 | Server = Source of Truth | DONE | همه مالی/سشن در سرور؛ ایجنت فقط مجری (`agent.py` قانون unlock-only-via-command) |
| 2 | Client غیرقابل اعتماد؛ validate مجدد | DONE | device-secret جدا، توکن کوتاه‌عمر، همه‌چیز سمت سرور (`api/agent.py`) |
| 3,127,128 | معماری سه‌بخشی + لایه‌بندی + ساختار پوشه‌ها | DONE | `server/ operator_app/ client_agent/ shared/ database/` |
| 162–164 | حفظ کد سالم، بدون ری‌رایت غول‌پیکر، گپ‌آنالیز | DONE | `GameNetPro-GAP-ANALYSIS.md`، توسعه مرحله‌ای با تست |
| 200 | مدل دامنه (مشتری→اعتبار→سشن→PC و …) | DONE | جداول + سرویس‌ها همین زنجیره را پیاده می‌کنند |
| 202 | ۲۰ قانون Cursor | PARTIAL | قانون ۲ (بکاپ قبل مایگریت) و ۱۴ (تمایز اینترنت/LAN) رعایت نشده — ثبت شد برای P5 |
| 211 | اولویت‌ها (صحت اول، ظاهر آخر) | DONE | بدون UI تزئینی؛ تمرکز بر integrity/مالی/ریکاوری |

### مشتری و احراز (§۳۶–§۳۹، §۹۶، §۱۱۵، §۱۳۹)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 36 | شناسه یکتا/دائمی مشتری | DONE | `customers(id, customer_number UNIQUE)` + تست |
| 37 | جستجوی مشتری | DONE | `api/customers.py` (نام/موبایل/گیم‌نیم/شماره) |
| 38–39 | داشبورد مشتری و Quick Play (سرعت عمل) | PARTIAL | فلو API کامل است؛ UI و endpointهای quick در P3-5 |
| 96 | عدم ذخیره plaintext پسورد/PIN | DONE | `security/passwords.py` + `customer_auth.pin_hash` + تست P0-1 |
| 115 | پروفایل مشتری | PARTIAL | endpointها هست؛ محدودسازی PII دستی بررسی شود |
| 139 | لاگین مشتری (ID/PIN) | MISSING | ⚠️ جدول `customer_auth` آماده ولی endpoint لاگین مشتری وجود ندارد — به P3-5 اضافه شد |

### اعتبار، VIP، پکیج، قیمت (§۳۱–§۳۵، §۴۰–§۴۱، §۴۸–§۴۹)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 31,33–34 | مبالغ INTEGER، چند اعتبار همزمان، انقضا | DONE | `006_ledgers.sql`، `credit_service.py`، تست‌ها |
| 32 | مدل Entitlement کامل | PARTIAL | فیلد `priority` جداگانه ندارد (اولویت سراسری از settings) |
| 35 | ممنوعیت اعتبار منفی + Debt با پرمیشن | PARTIAL | منفی ممنوع DONE؛ قابلیت Debt رسماً MISSING |
| 40 | موتور قیمت + Snapshot | DONE | `pricing_service.py` + `price_snapshot` در آیتم‌ها |
| 41 | محاسبه خودکار، ورود دستی محدود | PARTIAL | محاسبه خودکار DONE؛ پرمیشن جدا برای manual-amount MISSING |
| 48 | VIP (پلن/تمدید NOW و AFTER_EXPIRY) | DONE | `credit_service.grant_vip` + تست زنجیره |
| 49 | Package (ساعت/قیمت/انقضا/بانس) | DONE | `catalog` + grant مستقل + تست |

### فروش، پرداخت، ریفاند، تخفیف (§۴۲–§۴۷، §۹۴، §۱۳۶–§۱۳۷)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 42 | CASH/CARD/MIXED/OTHER + آداپتر کارتخوان | PARTIAL | CASH/CARD/BALANCE + اینترفیس `PaymentProvider`؛ MIXED با چند پرداخت ممکن است؛ OTHER صریح MISSING |
| 43 | Idempotency پرداخت + استیت‌ها | DONE | `X-Request-ID` + استیت‌ماشین با UNKNOWN + تست تکراری |
| 44 | موتور فروش یکپارچه | DONE | Sale→Items→Payments→Entitlement→Audit |
| 45 | ریفاند بدون حذف + حفظ فروش اصلی | DONE | `011_refunds.sql` + `refund_service` + تست ۱۱تایی |
| 46 | ثبت Override (who/why/before/after) | DONE | audit با old/new/reason/amount |
| 47 | تخفیف حساس با پرمیشن + سقف کانفیگ | DONE | `discount.apply` + `operator_max_discount_pct` + دلیل اجباری |
| 94,136–137 | عدم ویرایش مخرب مالی؛ ضد double | DONE | قیمت snapshot، بدون delete، سقف ریفاند، کلید idempotency |

### سشن و زمان (§۲۴، §۲۷–§۳۰، §۷۶–§۸۰، §۱۳۴–§۱۳۵، §۱۴۵–§۱۴۷، §۱۷۵)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 24 | Lease سشن (انقضا→PAUSE) | PARTIAL | lease روی heartbeat/presence پیاده است؛ جدول `session_leases` جدا MISSING |
| 27 | استیت‌ماشین سشن | CONFLICT | ما: CREATED/AUTHORIZED/ACTIVE/PAUSED/ENDED/CANCELLED/INTERRUPTED/CONNECTION_LOST؛ اسپک: …/PENDING/…/RECOVERING/…/EXPIRED — نگاشت مستند شود |
| 28 | زمان UTC/ISO در Core، بدون jdatetime | DONE | `utc_now_iso` همه‌جا؛ بدون jdatetime (grep تأیید) |
| 29 | تشخیص Clock Drift | MISSING | ⚠️ heartbeat ساعت کلاینت نمی‌فرستد — P5 |
| 30 | ردیابی مصرف (event/request/device/start/end) | PARTIAL | `session_consumptions` دارد ولی `request_id/device_id` ندارد |
| 76 | تایم‌لاین سشن | DONE | `session_events` + endpoint |
| 77 | Extend با حفظ تاریخچه | MISSING | ⚠️ هیچ endpoint تمدید سشن نیست — به P3-5 اضافه شد |
| 78 | انتقال اتمیک PC | DONE | `transfer` تک‌تراکنش + LOCK/UNLOCK + تست |
| 79 | اعتبار متعلق به مشتری نه سشن | DONE | consume از entitlement مشتری |
| 80 | قانون Logout | PARTIAL | رفتار ضمنی درست است (سشن آزاد، اعتبار می‌ماند) ولی endpoint/قانون صریح مستند نیست |
| 134–135 | ضد race سشن/پکیج | DONE | one-active ایندکس‌ها + تراکنش |
| 145–147 | شمارش معکوس سروری؛ عدم نمایش اعتبار فیک؛ کش غیرحساس | DONE | `server_time` + `session` در heartbeat؛ `state.json` غیرحساس |

### ارتباطات و تاب‌آوری (§۱۲–§۲۶، §۱۰۵–§۱۰۷، §۱۱۴، §۱۴۸–§۱۵۰)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 12–13 (شبکه/حضور) | presence در حافظه + فلاش دوره‌ای | DONE | `realtime/presence.py` (طراحی ضد رقابت SQLite) |
| 21–22 | هویت دستگاه (device_id، نه MAC) + ثبت‌نام | DONE | `device_code` + `device_credentials` جدا از مشتری |
| 23 | Heartbeat (بدون secret؛ پاسخ: زمان/lease/فرمان) | DONE | `api/agent.py` + `agent_service.heartbeat` |
| 25 | تمایز قطعی اینترنت از قطعی سرور | MISSING | ⚠️ فقط reachability سرور بررسی می‌شود — P5 (نیازمند تصمیم محصول) |
| 26 | ماتریس وضعیت اتصال | PARTIAL | سناریوهای اصلی (سرور/کلاینت/بازی/ری‌استارت) پوشش داده شده؛ اینترنت جدا نشده |
| 105 | REST + WebSocket | DONE | REST مدیریتی + WS ایجنت (`agent_ws.py`) |
| 106 | ساختار versioned پیام WS | PARTIAL | `type`-محور است؛ `message_id/version/request_id` ندارد |
| 107 | ایونت‌های WS | PARTIAL | HEARTBEAT/ACK/COMMAND/PING هست؛ SESSION_*/CREDIT_UPDATE/SERVER_NOTICE صریح MISSING |
| 114 | Server Push (pause/lock/message/…) | PARTIAL | LOCK/MESSAGE/UNLOCK و … via فرمان؛ MAINTENANCE و SESSION_UPDATE صریح MISSING |
| 148–150 | قطع→PAUSE، reconnect با backoff، ریکاوری idempotent | PARTIAL | همه DONE به‌جز jitter در backoff و پیام UI (UI نداریم) |

### ایجنت کلاینت (§۴، §۷، §۱۷، §۱۰۰)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 4 | جدایی Agent از UI (سرویس ویندوز) | PARTIAL | ایجنت headless مستقل DONE (`client_agent/`)؛ UI و سرویس‌بودن واقعی ویندوز DEFERRED |
| 7,100 | عدم دسترسی مشتری به config/secret/uninstall | PARTIAL | توکن حافظه‌ای + secret فقط در فایل کانفیگ؛ enforcement واقعی ویندوز با Kiosk (فاز ۵ اسپک) |
| 17 | عدم مزاحمت هنگام بازی تمام‌صفحه | DONE | ایجنت headless بدون UI/اورلی (by design) |

### Kiosk و بازی‌ها (§۵–§۶، §۸–§۲۰، §۱۰۸–§۱۰۹، §۱۱۱، §۱۱۳، §۱۷۸–§۱۷۹)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 5–6,8,19,179 | Kiosk/Lockdown واقعی + Maintenance Mode امن | MISSING | فقط `LockWorkStation` و بوت قفل‌شده؛ کل زیرسیستم kiosk DEFERRED (نیازمند تست روی Test PC واقعی) |
| 9–16,18,108–109,111,113,178 | کاتالوگ بازی، لانچرها، مانیتور پروسس، سوییچ بازی | MISSING | کامل — DEFERRED (بزرگ‌ترین بلوک جامانده؛ پس از P5) |

### PC و دستگاه‌ها (§۵۴–§۵۶، §۱۹۶)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 54 | موجودیت PC | PARTIAL | id/نام/وضعیت/agent_version/last_seen هست؛ IP/MAC/location/platform نیست |
| 55 | وضعیت‌های PC | CONFLICT | ما READY/BUSY/PAUSED داریم، اسپک AVAILABLE/OCCUPIED/UPDATING می‌خواهد — نگاشت مستند شود |
| 56 | سلامت PC | PARTIAL | cpu/mem/disk در heartbeat جمع می‌شود؛ جدول تاریخچه `pc_health` و دما MISSING |
| 196 | PS5 به‌عنوان Generic Device | MISSING | فیلد platform/device-type وجود ندارد — P5 (کوچک) |

### فرمان راه دور (§۵۹–§۶۲)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 59 | مجموعه فرمان‌ها | PARTIAL | LOCK/UNLOCK/MESSAGE/END_SESSION/SHUTDOWN/RESTART/SYNC هست؛ WAKE/MAINTENANCE/REFRESH/UPDATE نیست |
| 60 | آبجکت فرمان + استیت‌ها | PARTIAL | PENDING/SENT/ACKED/FAILED/EXPIRED؛ RUNNING/SUCCESS/TIMEOUT/CANCELLED صریح نیست |
| 61 | پرمیشن جداگانه برای عملیات حساس | PARTIAL | فقط `remote.execute` واحد؛ تفکیک shutdown/restart/unlock/… MISSING |
| 62 | تأیید دومرحله‌ای اضطراری | MISSING | هیچ فلو emergency نیست — با UI اپراتور (P4/P5) |

### موجودی و تجهیزات (§۶۳–§۶۷)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 63–64 | کالا + لجر موجودی (بدون تغییر مستقیم) | PARTIAL | P3-3 در حال انجام؛ `purchase_price/category` و انواع DAMAGE/LOSS/RETURN فعلاً نیست |
| 65 | مغایرت Expected/Actual + هشدار | MISSING | چک reconciliation موجودی در P3-3 اضافه می‌شود؛ هشدار با P4 |
| 66–67 | تجهیزات + تیکت تعمیرات | MISSING | DEFERRED (پس از P3؛ در TODO نیست — اضافه شود) |

### کاربران، نقش‌ها، شیفت، صندوق (§۶۸–§۷۱، §۹۷–§۹۹)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 68 | کارمند (پروفایل/شیفت/عملکرد) | PARTIAL | users+roles هست؛ API مدیریت کاربر و پروفایل MISSING |
| 69 | RBAC گرانولار + نقش‌های قابل‌تنظیم | PARTIAL | ۵ نقش + ۲۰ پرمیشن DONE؛ نقش ADMIN جدا و CRUD نقش MISSING |
| 70–71 | شیفت + مغایرت صندوق | DONE | `010_shifts.sql` + expected/actual/variance + تست |
| 97 | امنیت توکن (انقضا/ابطال/…) | PARTIAL | انقضا + ابطال DONE؛ rotation MISSING |
| 98–99 | خروج خودکار + ضد brute-force | PARTIAL | TTL توکن + lockout پنج‌تایی + audit؛ ریت‌لیمیت IP و rotation MISSING |

### آدیت و ضدتقلب (§۷۲–§۷۵، §۱۹۳–§۱۹۵)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 72 | کنترل‌های ضدتقلب | PARTIAL | authZ همه‌جا + audit + reconciliation + variance؛ موتور قانون/هشدار مخصوص fraud با P4 |
| 73–74 | آدیت کامل + زنجیره هش + عدم حذف | DONE | `audit_service` با prev_hash/hash + `audit-verify` + تست tamper |
| 75 | Soft Delete | MISSING | ⚠️ هیچ `deleted_at` نیست — P5 (کوچک، ولی باید قبل از UI) |
| 193–195 | رویداد امنیتی + داشبورد + کنترل مکمل دوربین | MISSING | فقط audit عمومی؛ جدول/داشبورد امنیتی با P4 |

### ریکاوری و پایداری (§۸۱–§۹۰، §۱۵۰، §۱۸۰، §۱۸۲)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 81–82 | ریکاوری کرش کلاینت/سرور | DONE | `workers/recovery.py` + `state.json` ایجنت + تست‌ها |
| 83 | حالت امن پس از corruption | DONE | integrity_check → safe_mode خودکار + میدل‌ور 503 |
| 84 | دیسک‌فول | MISSING | هیچ چک فضایی نیست — P4 (همراه health) |
| 85 | SQLite درست (WAL/FK/تراکنش/ایندکس) | DONE | pragmas در `db.py` + تراکنش‌ها |
| 86 | مایگریشن امن + بکاپ قبلش | PARTIAL | نسخه‌بندی DONE؛ بکاپ خودکار قبل مایگریت MISSING |
| 87–89 | بکاپ/ری‌استور (روزانه/دستی/retention/API امن) | MISSING | کامل — P4 |
| 90,150 | ورکرهای idempotent | DONE | lease/reconcile/recovery همه idempotent + تست |
| 180,182 | معیار پذیرش کرش؛ اتوماسیون روزانه | PARTIAL | ریکاوری DONE؛ زمان‌بندی روزانه (cron/thread) MISSING — P4 |

### مالی پیشرفته و یکپارچگی (§۹۲–§۹۳، §۹۵، §۱۳۲–§۱۳۳، §۱۳۸)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 92 | موتور reconciliation دوره‌ای | PARTIAL | ۷ گروه چک + تاریخچه اجراها؛ چک shift↔cash و inventory↔sale (دومی در P3-3) کم است؛ زمان‌بندی خودکار با P4 |
| 93,95 | ردیابی Sale→…→Consumption؛ بالانس قابل‌بازسازی | DONE | کلیدهای ref + لجر append-only + تست |
| 132–133,138 | رقابت اپراتورها/بالانس/موجودی | DONE | تراکنش + constraint + چک موجودی در کانفرم (تست همزمانی واقعی بار P5) |

### رزرو، صف، گروه (§۵۱–§۵۳)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 51 | رزرو + تشخیص تداخل | MISSING | P3-4 (بعدی) |
| 52–53 | صف مشتری + سشن گروهی | MISSING | ⚠️ حتی در TODO ریپو نیست — به TODO اضافه شود، پس از رزرو |

### گزارش، هشدار، داشبورد (§۵۷–§۵۸، §۱۱۶–§۱۲۲، §۱۵۳–§۱۵۴، §۱۸۱)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 57–58,153–154 | سلامت سرور/دیسک + دایاگنوستیک | PARTIAL | `/health` پایه + presence؛ باندل diagnostics و آستانه دیسک MISSING — P4 |
| 116–118 | گزارش‌ها + خروجی CSV/Excel/PDF + جستجوی سراسری | MISSING | P4 (فقط audit-list و presence خام موجود است) |
| 119–120 | هشدارها + معماری نوتیفیکیشن (تلگرام/…) | MISSING | P4 (اینترفیس + desktop؛ تلگرام اختیاری) |
| 121–122,181 | داشبورد exception-based مالک + چک‌لیست روزانه | MISSING | P4 |
| 50 | تاریخچه یکپارچه مشتری | PARTIAL | لجرها جدا جدا موجود؛ نمای یکپارچه با P4 |

### امنیت و کانفیگ (§۱۲۵–§۱۲۶، §۱۵۹–§۱۶۰، §۱۸۷، §۱۸۹، §۱۹۲)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 125 | TLS/احراز دستگاه/عدم plaintext secret | PARTIAL | احراز دستگاه DONE؛ TLS و secret-at-rest ایجنت تصمیم/پیاده MISSING — P5 |
| 126,159,189 | تنظیمات متمرکز/بدون magic-number/جدایی کانفیگ | DONE | جدول `settings` + اعتبارسنجی + تست (چند کلید آینده: lockdown، client-version…) |
| 160,187,192 | عدم هاردکد سکرت؛ فایل‌های امن؛ حریم لاگ | PARTIAL | هاردکدی نیست؛ سیاست حریم لاگ مستند نشده |

### خطاها و لاگ (§۱۱۰، §۱۵۱–§۱۵۲، §۱۵۵–§۱۵۸)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 110,155,157 | پیام فارسی مشتری + کد خطای GN-* + فرمت استاندارد | MISSING | فرمت پیش‌فرض FastAPI؛ با P5 (نیازمند UI هم هست) |
| 151–152 | لاگ مرحله‌ای + rotation | MISSING | فقط `print`؛ زیرساخت logging با P4/P5 |
| 156,158 | اعتبارسنجی API؛ عدم silent-exception | PARTIAL | auth/authZ/validation/audit/idempotency روی مسیرهای کلیدی؛ یک `except` عمدی مستند در lease-monitor |

### استقرار و نگهداشت (§۱۰۲–§۱۰۴، §۱۸۴–§۱۸۶، §۱۸۸، §۱۹۰–§۱۹۱، §۱۹۷–§۱۹۹)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 102–103 | آپدیت امضاشده + حداقل نسخه کلاینت | MISSING | `agent_version` ردیابی می‌شود؛ enforcement با P5 |
| 104 | ورژن API | DONE | `/api/v1` |
| 184–186 | PyInstaller + اینستالر آفلاین + بدون نیاز به پایتون | MISSING | P4 (installer/) |
| 188 | عدم وابستگی Core به jdatetime | DONE | grep تأیید: صفر |
| 190–191 | ارتقا/رول‌بک امن | MISSING | با P4 (همراه بکاپ/ری‌استور) |
| 197–۱۹۹ | آینده (شعب/کلاد/AI) | DEFERRED | طبق اسپک: بدون overengineering؛ AI هرگز source-of-truth نمی‌شود |

### تست و پذیرش (§۱۶۹–§۱۷۷، §۲۰۳–§۲۱۰)

| § | موضوع | وضعیت | شاهد |
|---|---|---|---|
| 169–170 | فازبندی و پایداری قبل از UI سنگین | DONE | دقیقاً همین مسیر رفته شده (Core اول، بدون UI) |
| 171 | لایه‌های تست | PARTIAL | unit/integration/API/DB/protocol/client/failure هست؛ E2E تمام‌حلقه و UI (نداریم) MISSING |
| 172 | ۳۰ سناریوی failure | PARTIAL | ~۱۸ پوشش (۱–۵،۹–۱۴،۲۶–۲۸،۳۰ + بخشی ۱۹)؛ جامانده: ۶–۸،۱۵–۱۸،۲۰–۲۵،۲۹(در P3-3)،بخشی ۱۹ — جزئیات در `docs/FAILURE_MATRIX.md` باید به‌روز شود |
| 173–174 | تست Kiosk/لانچ | DEFERRED | بدون آن زیرسیستم‌ها؛ روی Test PC واقعی بعداً |
| 175–177,180 | پذیرش سشن/پرداخت/ریفاند/کرش | DONE | هر چهار با تست سبز |
| 203–206,209 | پروتکل توسعه + گزارش فاز + DoD | PARTIAL | کد+تست+کامیت هر فاز DONE؛ گزارش رسمی فاز (§۲۰۶) و چند سند §۱۶۵ MISSING |
| 165–167 | مستندات + ماتریس + ثبت تعارض | PARTIAL | ۷ سند موجود (با این فایل)؛ غایب: MASTER_SPEC/API/WEBSOCKET/RECOVERY/BACKUP/DEPLOYMENT/TEST_PLAN/OPERATOR_GUIDE/ADMIN_GUIDE |

## ۳) CONFLICTهای ثبت‌شده (تصمیم‌های آگاهانه، نیازمند تأیید نهایی شما)

1. نام استیت‌های سشن/PC با §۲۷/§۵۵ موبه‌مو نیست (کاربردی‌تر انتخاب شده).
2. به‌جای استیت RECOVERING از PAUSED+`LINK_LOST` استفاده می‌شود (ساده‌تر، همان اثر).
3. لاگین مشتری فعلاً نیست؛ فلو جاری اپراتورمحور است (مشتری با PIN در فاز UI).
4. به‌جای جدول `session_leases` از lease روی presence استفاده شده (کارایی SQLite).
5. Solar: اینترنت vs LAN فعلاً تفکیک نشده (تک‌سرور LAN) — تصمیم محصول لازم دارد.

## ۴) کارهای جامانده‌ای که به نقشه اضافه می‌شود (بدون تغییر مسیر کلی)

- P3-4: رزرو (+ تداخل) | سپس صف و سشن گروهی (کوچک، همان فاز).
- P3-5: لاگین مشتری (PIN)، تمدید سشن (Extend)، quick-customer/quick-sale، شل اپراتور.
- P4: گزارش‌ها + خروجی + هشدار/تلگرام + داشبورد مالک + بکاپ/ری‌استور + اینستالر + logging + دیسک‌فول + زمان‌بندی روزانه + endpoint کاربران.
- P5: اینترنت/LAN، drift ساعت، jitter، کدهای خطا GN-*، فرمت خطا، soft-delete، ریت‌لیمیت، rotation توکن، min-client-version، TLS/at-rest، تست‌های همزمانی/ساعت، مستندات باقیمانده، گزارش‌های فاز.
- پس از P5 (فازهای اسپک ۵ و ۶): Kiosk واقعی، کاتالوگ/لانچر بازی، مانیتور پروسس، UIها (PyQt) — نیازمند Test PC ویندوزی.
