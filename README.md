## Własny Lepszy KSeF

Instrukcja instalacji: https://github.com/motowilk/wlasny-lepszy-ksef#instalacja-i-konfiguracja

## Czym jest ta aplikacja?

**Własny Lepszy KSeF** to lokalny system do obsługi obiegu faktur zintegrowany z Krajowym Systemem e-Faktur (KSeF). Aplikacja służy właścicielowi firmy lub wyznaczonemu pracownikowi do wystawiania faktur sprzedażowych, rejestracji ich w KSeF oraz pobierania i akceptowania do księgowania kosztowego faktur zakupowych. Zakwalifikowane faktury są zbierane w pakiety miesięczne i wysyłane do zewnętrznego biura księgowego.

## Dla kogo i po co?

Aplikacja jest przeznaczona dla właściciela małej lub średniej firmy (lub wyznaczonego pracownika), który:

- chce mieć **własny rejestr faktur** sprzedażowych i zakupowych z pełną historią zmian
- potrzebuje **automatycznej wysyłki faktur do KSeF** bez ręcznego wklejania XML-i w portal MF
- chce **importować faktury zakupowe z KSeF** i decydować, które trafiają do biura księgowego
- potrzebuje **śladu audytowego** — kto, kiedy, co zrobił z dokumentem
- chce **powiadomień e-mail/Slack** o wysłanych pakietach do biura księgowego
- potrzebuje prostego podziału ról — agent AI tworzy drafty, reviewer akceptuje, właściciel kwalifikuje i wysyła do biura

## Jak wygląda miesiąc pracy z aplikacją?

### Tydzień 1–4: codzienne operacje

**Faktury sprzedażowe (codziennie):**
1. Właściciel lub agent tworzy draft faktury sprzedażowej (ręcznie w UI lub przez API).
2. System wylicza kwoty, VAT, sumy.
3. Właściciel sprawdza i akceptuje fakturę.
4. W tle Scheduler wysyła XML do KSeF i czeka na potwierdzenie numeru KSeF.
5. Faktura otrzymuje oficjalny numer KSeF — gotowe.

**Faktury zakupowe (codziennie lub co kilka dni):**
1. Scheduler lub właściciel odpala import faktur zakupowych z KSeF za ostatnie dni.
2. System parsuje XML-e, deduplikuje i tworzy faktury zakupowe w rejestrze.
3. Właściciel przegląda nowe faktury zakupowe, kwalifikuje je do wysłania do biura księgowego lub odrzuca.

### Koniec miesiąca: wysyłka do biura księgowego

1. Właściciel generuje **pakiet miesięczny** — system zbiera wszystkie zakwalifikowane faktury z danego miesiąca w jedną paczkę.
2. Pakiet dostaje kod (np. `BATCH-2026-05-A1B2C3D4`) i jest wysyłany do biura księgowego.
3. Faktury w pakiecie zmieniają status na `sent_to_office`.
4. Biuro księgowe otrzymuje powiadomienie i księguje faktury w swoich systemach.

### Ciągłe w tle:

- Scheduler co kilka minut sprawdza kolejkę zadań i przetwarza: wysyłki, pollingi statusów, powiadomienia, importy.
- Heartbeat workera jest widoczny w bazie — wiadomo, czy procesy działają.
- Pełna historia eventów pozwala w dowolnym momencie prześledzić, co się działo z konkretną fakturą.

### Podsumowanie wartości:

| Bez aplikacji | Z aplikacją |
|---|---|
| Ręczne logowanie do portalu KSeF | Automatyczna wysyłka i polling w tle |
| Excel z listą faktur zakupowych | Rejestr z importem z KSeF, filtrami, statusami |
| Brak historii zmian | Pełny audit trail z eventami |
| Brak procesu kwalifikacji | Workflow: draft → review → approve → KSeF → biuro |
| Ręczne kompletowanie faktur dla biura | Automatyczne pakiety miesięczne z jednym kliknięciem |
| Brak potwierdzenia wysyłki | Statusy i powiadomienia e-mail/Slack |

Dashboard:
<img width="3476" height="2046" alt="image" src="https://github.com/user-attachments/assets/101f6ab4-ab1a-4a1f-af15-33493e60aa30" />
Draft faktury:
<img width="2368" height="1926" alt="image" src="https://github.com/user-attachments/assets/29fa085b-656c-4750-9759-e32bb92789c9" />
Zakupowe:
<img width="2366" height="832" alt="image" src="https://github.com/user-attachments/assets/40cef24f-15de-4bd1-aba2-8a73e509aeee" />
Faktura zakupowa z KSeF:
<img width="1842" height="1964" alt="image" src="https://github.com/user-attachments/assets/79c4e375-4562-4ba3-9d25-abbcd357dfbe" />
Pakiety faktur do wysyłki do księgowości:
<img width="1786" height="484" alt="image" src="https://github.com/user-attachments/assets/6aba1e58-ecd3-4e27-9d59-2350d6775e68" />
Widok pakietu:
<img width="1818" height="1100" alt="image" src="https://github.com/user-attachments/assets/f97f92e4-9e57-493e-8db6-3f02511e6829" />
Kontrahenci:
<img width="1790" height="278" alt="image" src="https://github.com/user-attachments/assets/92611512-f477-43d7-90c9-615a5d18a388" />
Widok kontrahenta:
<img width="1808" height="1510" alt="image" src="https://github.com/user-attachments/assets/eae6a6dd-a1f1-4832-84df-0ef97b87c28b" />


## Aktualna funkcjonalność aplikacji

Po skonfigurowaniu środowiska aplikacja udostępnia kompletny lokalny system do obsługi obiegu faktur w modelu KSeF ERP.

### 1. Model dostępu i uwierzytelnianie

**Interfejs WWW (`/ui`)** — logowanie przez formularz HTML z sesją cookie:
- Po wpisaniu loginu i hasła serwer ustawia podpisany `HttpOnly` cookie (`session`).
- Opcjonalna weryfikacja TOTP (Google Authenticator, Aegis) jako drugi krok logowania.
- Wylogowanie przez `/ui/logout`.

**REST API (`/api/*`)** — HTTP Basic Auth (dla Swagger i klientów API).

- Hasła przechowywane jako hashe `bcrypt_sha256`.
- Obsługiwane role: `admin`, `agent`, `reviewer`, `owner`, `viewer`.
- Konto `admin` tworzone skryptem inicjalizacyjnym na podstawie `ADMIN_DEFAULT_PASSWORD` z `.env`.

### 2. Interfejs WWW

UI obejmuje:

- dashboard z licznikami faktur, powiadomień i pakietów księgowych
- listę faktur sprzedażowych i zakupowych
- formularz tworzenia nowej faktury sprzedażowej
- widok szczegółów faktury z liniami, stronami dokumentu, eventami i payloadami
- pobieranie PDF faktury (wizualizacja w formacie KSeF)
- listę pakietów księgowych i szczegóły pakietu
- listę powiadomień
- zarządzanie kontrahentami (lista, formularz dodawania/edycji)
- zarządzanie użytkownikami (lista, formularz tworzenia, konfiguracja TOTP)

### 3. Zarządzanie fakturami

Warstwa API udostępnia pełną obsługę draftów i rejestru faktur:

- tworzenie, aktualizowanie i przeliczanie draftów
- listowanie z filtrowaniem po `direction_code`, `ksef_status_code`, `accounting_status`, `erp_status`, `review_status`
- stronicowanie przez `limit` i `offset`
- walidacja biznesowa i XSD (schemat FA(3) v1-0E)
- akceptacja i zapisanie do kolejki wysyłki KSeF
- pobieranie historii eventów i metadanych payloadów

W trakcie pracy z fakturą system utrzymuje: dane nagłówka, strony dokumentu, pozycje, sumy, podsumowania VAT, statusy obiegu, historię eventów i payloady XML.

### 4. Walidacja i generowanie danych KSeF

Przed akceptacją faktura przechodzi walidację biznesową. Po sukcesie aplikacja:

- generuje XML faktury zgodny z FA(3) v1-0E
- liczy hash SHA-256 dokumentu XML
- zapisuje XML jako payload typu `KSEF_XML`
- waliduje XML względem schematu XSD
- oznacza dokument jako zaakceptowany
- tworzy zadanie integracyjne `SEND_TO_KSEF`

### 5. Integracja z KSeF

Dwa tryby pracy: `mock` (development) i `live` (produkcja z rzeczywistym API KSeF).

Workflow integracyjny:
- wysłanie XML do KSeF i zapis numeru referencyjnego
- w trybie `mock` — natychmiastowa akceptacja z lokalnym numerem KSeF
- w trybie `live` — cykliczne odpytywanie (`POLL_KSEF_STATUS`) aż do `ACCEPTED`/`REJECTED`
- zapis eventów integracyjnych i payloadów odpowiedzi

### 6. Obsługa faktur zakupowych

- listowanie i szczegóły faktur zakupowych
- pobieranie faktur z API KSeF dla zakresu dat (`POST /api/purchase-invoices/fetch-from-ksef`)
- import XML FA(3) z pliku (`python scripts/import_purchase_xml.py <plik>`)
- deduplikacja po `ksef_number` i `invoice_number`
- kwalifikowanie lub odrzucanie faktury z procesu kosztowego
- parser rozpoznaje strukturę FA(3) v1-0E: Podmiot1=SELLER, Podmiot2=BUYER, kody VAT (23, 22, 8, 7, 5, 4, 3, 0, zw, oo, np, oss)

### 7. Pakietowanie i wysyłka do biura księgowego

- kwalifikacja faktury do wysyłki (`POST /api/invoices/{id}/qualify`)
- dodanie do pakietu (`POST /api/invoices/{id}/add-to-batch`)
- generowanie pakietów miesięcznych dla zakwalifikowanych faktur
- listowanie, szczegóły i usuwanie faktury z pakietu (przed wysyłką)

Statusy procesu (`accounting_status`): `new` → `qualified` → `batched` → `sent_to_office` / `rejected`

### 8. Powiadomienia

Kanały: **E-mail** (SMTP z auto-rozpoznawaniem TLS) i **Slack**.

- tworzenie i wysyłka powiadomień dla faktur i pakietów
- automatyczne powiadomienia po wysłaniu pakietu do biura
- historia powiadomień z statusami i payloadami
- eventy: `NOTIFICATION_CREATED`, `NOTIFICATION_SENT`, `NOTIFICATION_FAILED`

### 9. Zarządzanie użytkownikami i rolami

- listowanie użytkowników z rolami, tworzenie nowych kont
- nadawanie i aktualizacja ról
- normalizacja loginów, walidacja duplikatów, hashowanie haseł

### 10. Endpointy pomocnicze

- `/health` — sprawdzenie dostępności
- `/docs` — Swagger
- `/api/me` — dane bieżącego użytkownika
- endpointy agentowe: podgląd kolejki zadań, lista draftów

### 11. Zdarzenia i ślad audytowy

Dla dokumentów zapisywane są:
- eventy biznesowe (utworzenie, aktualizacja, akceptacja, kwalifikacja, pakietowanie)
- eventy integracyjne (wysyłka do KSeF, akceptacja/odrzucenie, powiadomienia)
- payloady XML/JSON
- znaczniki czasu i informacje o aktorze

### 12. Przetwarzanie asynchroniczne

**Scheduler** (APScheduler) cyklicznie pobiera zadania z bazy w konfigurowalnym interwale. Obsługiwane typy:

- `SEND_TO_KSEF`, `POLL_KSEF_STATUS`, `SEND_ACCOUNTING_BATCH`, `FETCH_KSEF_PURCHASES`

Mechanizm: blokada `skip_locked`, retry z wykładniczym backoffem (`delay = min(300, 5 × 2^(attempts−1))`), monitorowanie heartbeat z fazami (`idle`/`processing`/`cooldown`).

### 13. Generowanie PDF faktury (wizualizacja KSeF)

Każda faktura może zostać pobrana jako PDF odzwierciedlający strukturę schematu FA(3) v1-0E.

**Endpoint:** `GET /ui/invoices/{id}/pdf`

**Zawartość PDF:**
- Nagłówek "Krajowy System e-Faktur" z rodzajem faktury (RodzajFaktury)
- Metadane: numer faktury (P_2), numer KSeF, data wystawienia (P_1), data sprzedaży (P_6), waluta (KodWaluty), kurs
- Bloki Podmiot1 (Sprzedawca) i Podmiot2 (Nabywca) z NIP, nazwą, adresem
- Tabela pozycji (FaWiersz): NrWierszaFa, P_7, P_8A, P_8B, P_9A, P_10, P_11, P_12, P_11Vat
- Podsumowanie stawek VAT (P_13_x / P_14_x) z sumą brutto (P_15)
- Sekcja Płatność: FormaPlatnosci, TerminPlatnosci, RachunekBankowy/NrRB
- Kod QR do weryfikacji w KSeF (KOD I — faktury online)

**Kod QR (specyfikacja KOD I):**

```
https://qr.ksef.mf.gov.pl/invoice/{NIP_sprzedawcy}/{DD-MM-RRRR}/{SHA256_Base64URL}
```

SHA256 = Base64URL-encoded hash XML faktury (pole `xml_sha256`: hex → bytes → base64url bez paddingu).


---

## Instalacja i konfiguracja

### Założenia

- Python 3.11+
- MySQL 8.0+ (lokalnie lub Docker), kodowanie `utf8mb4`
- Git (opcjonalnie)

### Krok 1. Przejdź do katalogu aplikacji

```bash
cd ksef_app
```

### Krok 2. Utwórz i aktywuj środowisko wirtualne

**macOS / Linux:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### Krok 3. Zainstaluj zależności systemowe

WeasyPrint (generowanie PDF) wymaga bibliotek systemowych Pango i GLib.

**macOS (Homebrew):**

```bash
brew install pango glib
```

Jeśli używasz Pythona spoza Homebrew (np. z python.org), dodaj do `~/.zshrc`:

```bash
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/lib:$DYLD_FALLBACK_LIBRARY_PATH"
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf2.0-0
```

**Linux (Fedora/RHEL):**

```bash
sudo dnf install pango gdk-pixbuf2
```

**Windows:**

WeasyPrint na Windows wymaga GTK3. Zainstaluj z: https://github.com/nickvdyck/weasyprint-win/releases lub przez MSYS2:

```
pacman -S mingw-w64-x86_64-pango
```

### Krok 4. Zainstaluj pakiety Python

```bash
python3 -m pip install --upgrade pip
pip install -r requirements.txt
```

### Krok 5. Utwórz bazę danych i użytkownika

Połącz się z MySQL jako administrator i wykonaj:

```sql
CREATE DATABASE IF NOT EXISTS ksef_erp
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'ksef_user'@'%' IDENTIFIED BY 'change_me';
GRANT ALL PRIVILEGES ON ksef_erp.* TO 'ksef_user'@'%';
FLUSH PRIVILEGES;
```

Połączenie z MySQL:

```bash
# Docker:
docker exec -it <nazwa_kontenera_mysql> mysql -uroot -p

# Lokalna instalacja:
mysql -u root -p
```

### Krok 6. Utwórz plik konfiguracyjny `.env`

**macOS / Linux:**

```bash
cp .env.example .env
```

**Windows (PowerShell):**

```powershell
Copy-Item .env.example .env
```

### Krok 7. Uzupełnij konfigurację w `.env`

Ustaw co najmniej:

```env
APP_HOST=127.0.0.1
APP_PORT=8000
BASE_URL=http://127.0.0.1:8000

DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=ksef_erp
DB_USER=ksef_user
DB_PASSWORD=change_me   # ustaw silne hasło!

SECRET_KEY=<wygenerowany_losowy_klucz>
KSEF_MODE=mock

SMTP_HOST=localhost
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@ksef.local
DEFAULT_NOTIFICATION_EMAIL=biuro@example.com

LOG_LEVEL=INFO
LOG_DIR=logs

SCHEDULER_INTERVAL=10
SCHEDULER_STALE_SECONDS=600
UI_SESSION_MAX_AGE=43200

ADMIN_DEFAULT_PASSWORD=<haslo_dla_admin>
```

Wygeneruj `SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Krok 8. Utwórz schemat bazy

**Nowa baza (pierwsze uruchomienie):**

```bash
python3 scripts/create_tables.py
alembic stamp head
```

**Aktualizacja istniejącej bazy:**

```bash
alembic upgrade head
```

### Krok 9. Załaduj dane słownikowe

```bash
python3 scripts/seed_reference_data.py
```

Ładuje: kierunki faktur (SALE, PURCHASE), typy, statusy KSeF, role stron, role użytkowników. Bezpieczne do wielokrotnego uruchomienia.

### Krok 10. Utwórz konto administratora

```bash
python3 scripts/create_admin.py
```

Tworzy użytkownika `admin` z hasłem z `ADMIN_DEFAULT_PASSWORD`. Nie nadpisuje istniejącego konta.

### Krok 11. Uruchom aplikację

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Adresy:
- UI: http://127.0.0.1:8000/ui
- Swagger: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health

### Krok 12. Uruchom procesy w tle (opcjonalnie)

Wymagane do obsługi zadań asynchronicznych (wysyłka KSeF, polling, powiadomienia):

```bash
python3 -m app.workers.scheduler
```

### Krok 13. Przełącz na tryb live (opcjonalnie)

Aby podłączyć rzeczywisty KSeF, ustaw w `.env`:

```env
KSEF_MODE=live
KSEF_API_URL=https://api.ksef.mf.gov.pl/v2
KSEF_TOKEN=<twój_token_ksef>
KSEF_NIP=<nip_podmiotu>
```

| Aspekt | `mock` | `live` |
|---|---|---|
| Wysyłka XML | pominięta | HTTP POST do KSeF API |
| Numer KSeF | generowany lokalnie | nadawany przez MF |
| Polling statusu | pominięty | zadanie `POLL_KSEF_STATUS` |

Po zmianie zrestartuj aplikację i scheduler.

### Krok 14. Uruchom testy

```bash
python3 -m pytest tests
```

| Plik | Zakres |
| --- | --- |
| `test_invoice_service.py` | Wyliczenia kwot, rabatów i VAT |
| `test_ksef_import.py` | Parsowanie XML FA(3) v1-0E |
| `test_job_worker.py` | Logika zadań: claimowanie, retry, statusy |
| `test_schema_constraints.py` | Constrainty schematu bazy |
| `test_security_review.py` | Testy bezpieczeństwa |

---

## Schemat bazy danych

Baza `ksef_erp` po uruchomieniu migracji Alembic:

### Zarządzanie dostępem

| Tabela | Zawartość |
| --- | --- |
| `app_user` | Konta użytkowników z hasłami (bcrypt_sha256), statusami i opcjonalnym TOTP |
| `app_role` | Role: `admin`, `agent`, `reviewer`, `owner`, `viewer` |
| `app_user_role` | Powiązania użytkowników z rolami |

### Rejestry dokumentów

| Tabela | Zawartość |
| --- | --- |
| `invoice` | Główny rejestr faktur z pełnym cyklem życia |
| `invoice_line` | Pozycje z podatkami, kodami procedur i reverse charge |
| `invoice_party` | Strony dokumentów: sprzedawca, nabywca |
| `invoice_payment` | Warunki i informacje o płatności |
| `invoice_vat_summary` | Podsumowania VAT per stawka |
| `invoice_relation` | Powiązania między fakturami (np. korekta) |
| `invoice_attachment` | Załączniki |

### Integracja i workflow

| Tabela | Zawartość |
| --- | --- |
| `invoice_payload` | Payloady XML i odpowiedzi z KSeF |
| `invoice_event` | Historia zdarzeń: tworzenie, edycja, akceptacja, wysyłka |
| `ksef_session` | Sesje integracyjne z KSeF |
| `ksef_session_invoice` | Powiązanie faktur z sesjami KSeF |
| `integration_job` | Kolejka zadań asynchronicznych |

### Procesy księgowe i powiadomienia

| Tabela | Zawartość |
| --- | --- |
| `accounting_batch` | Pakiety miesięczne |
| `accounting_batch_invoice` | Faktury w pakietach |
| `notification_log` | Historia powiadomień (e-mail, Slack) |

### Monitorowanie i słowniki

| Tabela | Zawartość |
| --- | --- |
| `worker_heartbeat` | Stan workerów: faza, bieżące zadania |
| `party` | Słownik kontrahentów |
| `dicts` | Słowniki systemowe (kierunki, typy, statusy, role) |

### Statusy i przepływy

- **`ksef_status_code`**: `DRAFT` → `GENERATED` → `QUEUED` → `SENT` → `PROCESSING` → `ACCEPTED`/`REJECTED`
- **`erp_status`**: `DRAFT_CREATED` → `READY_FOR_REVIEW` → `APPROVED` → `QUEUED_FOR_KSEF` → `SENT_TO_KSEF` → `KSEF_ACCEPTED` → `READY_FOR_ACCOUNTING` → `ACCOUNTING_BATCHED` → `SENT_TO_OFFICE`
- **`accounting_status`**: `new` → `qualified` → `batched` → `sent_to_office` / `rejected`
- **`review_status`**: `PENDING` → `APPROVED` / `REJECTED`

### Migracje Alembic

| Migracja | Opis |
| --- | --- |
| `20260514_0001` | CASCADE FK, unique constraint batch invoice |
| `20260514_0002` | Tabela `notification_log`, `totp_secret` w `app_user` |
| `20260514_0003` | Tabela `worker_heartbeat` |
| `20260515_0001` | Unique constraint `invoice.invoice_number` |
| `20260515_0002` | Kolumny `phase`, `current_jobs_json` w `worker_heartbeat` |
| `20260516_0001` | Rola `accountant` → `owner`, migracja statusów |
| `20260516_0002` | Kolumna `send_at` w `accounting_batch` |
| `20260516_0003` | Okres `WEEK` w `accounting_batch` |
| `20260516_0004` | Kolumna `last_tick_at` w `worker_heartbeat` |
