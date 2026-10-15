# Store listing drafts (Google Play + App Store)

DRAFT. Verify every answer against the shipped build before submitting; the app is still mock-data only (see `OWNER_GUIDE.ar.md` section 2). Do not publish claims about prices, suppliers or coverage that are not real at launch time.

## 1. Title / العنوان
- AR: مُوَرِّد - توريد من المصنع إلى بابك (<= 30 chars; check store limit)
- EN: Factory Finder - Sourcing Made Easy (<= 30)
- iOS subtitle EN: Suppliers, landed cost, tracking / AR: موردون وكلفة كاملة وتتبع

## 2. Short description (Play, <= 80 chars)
- AR: ابحث عن موردين ومصانع، واحسب الكلفة الكاملة حتى بابك، وتابع شحنتك.
- EN: Find suppliers, see the full landed cost to your door, and track shipments.

## 3. Long description
**AR**
مُوَرِّد منصة توريد عالمية: ابحث عن منتجات ومواد أولية وخطوط إنتاج (جديدة ومستعملة)، وقارن الموردين مع تقييم الثقة، واحسب الكلفة التقديرية الكاملة حتى مدينتك (شحن داخلي، بحري أو جوي أو بري، جمارك وضرائب، نقل داخلي) بعملتك.

- بحث وفلاتر وفرز للمنتجات والموردين
- درجة ثقة للمورد وتوثيق الأعمال
- حاسبة الكلفة الكاملة مع مقارنة الخيارات ونطاق تقديري
- انشر طلباً واستقبل عروضاً من الموردين ثم اقبل العرض
- محادثات مباشرة مع الموردين وإرفاق الصور
- تتبع الشحنات (حاوية، بوليصة جوية، سفينة) وتنبيهات الأسعار
- مساعد ذكي بالعربية والإنكليزية
- واجهة عربية بالكامل (من اليمين لليسار) والإنكليزية لغة ثانية

تنبيه: الأسعار والرسوم الجمركية والرموز الجمركية (HS) تقديرية للإرشاد فقط، وليست استشارة جمركية أو قانونية. المنصة وسيط ولا تضمن جودة البضاعة.

**EN**
Factory Finder is a global sourcing platform. Search products, raw materials and production lines (new or used), compare suppliers with a trust score, and see the estimated full landed cost to your city (inland haul, sea/air/land freight, duties and taxes, final delivery) in your currency.

- Search, filters and sorting for products and suppliers
- Supplier trust score and business verification
- Landed-cost calculator with option comparison and estimate ranges
- Post a request, receive supplier offers, accept one
- In-app chat with suppliers, with photo attachments
- Shipment tracking (container, air waybill, vessel) and price alerts
- Arabic/English assistant
- Arabic-first, fully right-to-left, English second

Note: prices, duties and HS codes are estimates for guidance only, not customs or legal advice. The platform is an intermediary and does not guarantee goods quality.

## 4. Keywords (iOS, <= 100 chars, comma separated)
- EN: sourcing,suppliers,factory,import,China,freight,landed cost,customs,wholesale,shipment tracking
- AR (Arabic storefront): استيراد,موردين,مصانع,شحن,جمارك,الصين,تجارة,جملة,تتبع شحنة,مواد أولية

## 5. Categories
- Google Play: Business (alt: Shopping)
- App Store: primary Business, secondary Shopping (alt: Productivity)
- Content: user-generated listings, chat and requests.

## 6. Google Play Data safety (draft, based on service READMEs)
Collection is by the platform backend (gateway, media, messaging, rfq, notifications, tracking). No third-party analytics or ads SDK is in the app. Re-verify after adding Firebase/FCM or any SDK.

| Data type | Collected | Shared with third parties | Purpose | Optional | Notes |
|---|---|---|---|---|---|
| Email address | Yes | No | Account management | No | Account login; digest e-mail address optional |
| Name / company, phone | Yes (profile) | No | Account, communication | Yes | |
| User IDs | Yes | No | App functionality | No | |
| Photos | Yes | No | App functionality | Yes | Listing photos, avatars, chat attachments; EXIF/GPS stripped on upload |
| Other files / documents | Yes | No | Business verification | Yes | Verification documents stored privately, visible to owner and admins |
| Messages | Yes | No | App functionality | No | Chat with suppliers |
| Other user-generated content | Yes | No | App functionality | Yes | Listings, requests, offers, reviews |
| Purchase / financial info | Metadata only | No | App functionality | Yes | Invoice amounts, status, payer/payee ids; no card numbers (no card payments; USDT public address only). Re-check if payments go live |
| Device or other IDs | Yes if push enabled | FCM provider only if enabled | Notifications | Yes | Device push tokens |
| Approximate location | No | - | - | - | Destination city is chosen by the user, not read from GPS |
| App activity / analytics | No | - | - | - | |
| Crash logs / diagnostics | No (server request logs only, no tokens/queries) | - | - | - | |

- Encrypted in transit: Yes (HTTPS required for release; verify).
- Deletion request: required. Account deletion screen does NOT exist yet; add before submission and provide a web deletion URL.
- Data not sold. Not used for ads.

## 7. App Store privacy labels (draft)
- Data linked to you: contact info (email, name, phone), user content (photos, messages, listings), identifiers (user id, device token if push), other (verification documents).
- Data used to track you: none. No tracking, no ATT prompt.
- Purposes: app functionality, account management. No analytics, no advertising.
- Permissions strings are in `apps/mobile/tool/ci_prepare_platforms.sh` (photo library, camera).

## 8. Age rating notes
- Google (IARC): contains user-generated content and user interaction (chat); no violence, gambling, or mature content by design; shares no precise location. Expected: 12+/Everyone-10+ range; answer questionnaire honestly.
- Apple: UGC present, so provide report and block mechanisms (listing report and chat abuse filter exist; verify blocking of users) and contact info. Suggested 12+ or 17+ is not needed unless unrestricted web access exists (it does not). Answer "no" for gambling, medical, alcohol content in the app itself, but note listings are user-submitted and moderated.
- Not directed at children; minimum age 18 (business use). Put that in the terms.

## 9. Review notes
- Provide a demo account (create one before review) and mention mock mode vs live server.
- Explain crypto payments (USDT) apply to physical goods commissions only if enabled; check Apple guideline on external payments before enabling in iOS builds.
- Disclose that customs and cost figures are estimates.

## 10. Screenshots checklist
Both languages (AR first, RTL), at minimum: 
- [ ] Discover feed
- [ ] Search results with filters
- [ ] Listing detail with trust factors
- [ ] Supplier page with verification badge
- [ ] Landed-cost calculator results (comparison)
- [ ] Requests and offers / deal summary
- [ ] Chat
- [ ] Shipment tracking timeline
- [ ] Assistant
- [ ] Settings (language, theme, currency)
Sizes: Play phone 16:9 or 9:16 (min 2 images, up to 8), feature graphic 1024x500, icon 512x512. App Store: 6.9" / 6.5" iPhone sets (and iPad if supported), 1290x2796 style sizes; verify current required sizes. Use clearly labeled demo data; do not show real brand logos you do not own.
