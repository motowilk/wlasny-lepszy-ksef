## Własny Lepszy KSeF

Instrukcja instalacji: https://github.com/motowilk/wlasny-lepszy-ksef#instalacja-i-konfiguracja 

## Czym jest ta aplikacja?

**Własny Lepszy KSeF** to lokalny system do obsługi obiegu faktur zintegrowany z Krajowym Systemem e-Faktur (KSeF). Aplikacja służy właścicielowi firmy lub wyznaczonemu pracownikowi do wystawiania faktur sprzedażowych, rejestracji ich w KSeF oraz pobierania i akceptowania do księgowania kosztowego faktur zakupowych. Zakwalifikowane faktury są zbierane w batche miesięczne i wysyłane do zewnętrznego biura księgowego.

## Dla kogo i po co?

Aplikacja jest przeznaczona dla właściciela małej lub średniej firmy (lub wyznaczonego pracownika), który:

- chce mieć **własny rejestr faktur** sprzedażowych i zakupowych z pełną historią zmian
- potrzebuje **automatycznej wysyłki faktur do KSeF** bez ręcznego wklejania XML-i w portal MF
- chce **importować faktury zakupowe z KSeF** i decydować, które trafiają do biura księgowego
- potrzebuje **śladu audytowego** — kto, kiedy, co zrobił z dokumentem
- chce **powiadomień e-mail/Slack** o wysłanych batchach do biura księgowego
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

1. Właściciel generuje **batch miesięczny** — system zbiera wszystkie zakwalifikowane faktury z danego miesiąca w jedną paczkę.
2. Batch dostaje kod (np. `BATCH-2026-05-A1B2C3D4`) i jest wysyłany do biura księgowego.
3. Faktury w batchu zmieniają status na `sent_to_office`.
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
| Ręczne kompletowanie faktur dla biura | Automatyczne batche miesięczne z jednym kliknięciem |
| Brak potwierdzenia wysyłki | Statusy i powiadomienia e-mail/Slack |

<img width="2912" height="1284" alt="image" src="https://github.com/user-attachments/assets/72832e1f-7572-45a8-84db-c72bb9203fc9" />
Statusy faktury:
<img width="2014" height="1924" alt="image" src="https://github.com/user-attachments/assets/ea5669ea-86be-47fd-9051-d88189e09da6" />
Kontrahenci:
<img width="2046" height="270" alt="image" src="https://github.com/user-attachments/assets/cf26e6bf-782e-4d57-92ec-9e89a7a81d7e" />
Użytkownicy:
<img width="2026" height="264" alt="image" src="https://github.com/user-attachments/assets/97f3c363-62e6-4a2e-8148-453915b86e9a" />


## Aktualna funkcjonalność aplikacji

Po skonfigurowaniu środowiska aplikacja udostępnia kompletny lokalny system do obsługi obiegu faktur w modelu KSeF ERP. Poniżej znajduje się opis aktualnych możliwości wynikających z bieżącego kodu aplikacji.

### 1. Model dostępu i uwierzytelnianie

**Interfejs WWW (`/ui`)** — logowanie przez formularz HTML z sesją cookie:
- Użytkownik wchodzi na `/ui` → zostaje przekierowany do `/ui/login`.
- Po wpisaniu loginu i hasła serwer ustawia podpisany `HttpOnly` cookie (`session`) i przekierowuje do dashboardu.
- Jeśli konto ma ustawiony `totp_secret`, po haśle pojawia się drugi krok weryfikacji kodem TOTP (aplikacja uwierzytelniająca, np. Google Authenticator, Aegis).
- Wylogowanie przez `/ui/logout` — cookie jest kasowany.

**REST API (`/api/*`)** — HTTP Basic Auth (dla Swagger i klientów API).

- Hasła są przechowywane jako hashe `bcrypt_sha256`; stare hashe `bcrypt` są rozpoznawane i weryfikowane (wsteczna kompatybilność).
- Po poprawnym logowaniu aktualizowana jest data ostatniego logowania użytkownika.
- Dostęp do operacji jest ograniczany rolami systemowymi.
- Obsługiwane role: `admin`, `agent`, `reviewer`, `owner`, `viewer`.
- Konto `admin` jest tworzone skryptem inicjalizacyjnym na podstawie `ADMIN_DEFAULT_PASSWORD` z `.env`.

**Konfiguracja 2FA (TOTP):**

Aby włączyć weryfikację dwuetapową dla konta, ustaw pole `totp_secret` w tabeli `app_user` na base32-zakodowany sekret (np. generowany przez `pyotp.random_base32()`). Konto bez ustawionego `totp_secret` loguje się jednoetapowo.

### 2. Interfejs WWW

Interfejs WWW jest dostępny pod adresem `/ui` i służy do codziennej obsługi danych bez potrzeby ręcznego wywoływania endpointów API.

UI obejmuje obecnie:

- dashboard z licznikami faktur, powiadomień i batchy księgowych
- listę faktur sprzedażowych
- listę faktur zakupowych
- formularz tworzenia nowej faktury sprzedażowej
- widok szczegółów faktury z liniami, stronami dokumentu, eventami i payloadami integracyjnymi
- listę batchy księgowych
- szczegóły pojedynczego batcha księgowego
- listę powiadomień
- zarządzanie kontrahentami (lista i formularz dodawania/edycji)
- zarządzanie użytkownikami (lista, formularz tworzenia, konfiguracja TOTP)

Z poziomu UI można obecnie:

- utworzyć nowy draft faktury sprzedażowej
- obejrzeć szczegóły faktury wraz z historią zdarzeń
- zaakceptować fakturę i przekazać ją do kolejki integracyjnej KSeF
- przeglądać i dodawać kontrahentów
- zarządzać użytkownikami i ich konfiguracją 2FA (TOTP)

### 3. Zarządzanie fakturami sprzedażowymi i ogólnym rejestrem faktur

Warstwa API udostępnia pełną obsługę draftów i rejestru faktur.

Aktualnie możliwe jest:

- tworzenie draftu faktury przez API
- pobieranie listy faktur z filtrowaniem po `direction_code`, `ksef_status_code`, `accounting_status`, `erp_status`, `review_status`
- stronicowanie list przez `limit` i `offset`
- pobieranie szczegółów pojedynczej faktury
- aktualizowanie draftu przed akceptacją
- ponowne przeliczenie faktury na podstawie aktualnych danych
- uruchomienie walidacji biznesowej faktury
- akceptacja faktury i zapisanie jej do kolejki wysyłki KSeF
- pobieranie historii eventów faktury
- pobieranie metadanych zapisanych payloadów integracyjnych

W trakcie pracy z fakturą aplikacja utrzymuje i aktualizuje między innymi:

- dane nagłówka dokumentu
- strony dokumentu, takie jak sprzedawca i nabywca
- pozycje faktury
- sumy netto, VAT i brutto
- podsumowania VAT
- statusy obiegu biznesowego i integracyjnego
- historię eventów technicznych i biznesowych
- payload XML do KSeF i payloady odpowiedzi integracyjnych

### 4. Walidacja i generowanie danych KSeF

Przed akceptacją faktura przechodzi walidację biznesową. Jeżeli walidacja zakończy się sukcesem, aplikacja:

- generuje XML faktury
- liczy hash SHA-256 dokumentu XML
- zapisuje XML jako payload typu `KSEF_XML`
- oznacza dokument jako zaakceptowany biznesowo
- tworzy zadanie integracyjne `SEND_TO_KSEF`

Dodatkowo aplikacja waliduje wygenerowany XML dokumentu faktury względem schematu XSD FA(3) v1-0E (`schemat_FA(3)_v1-0E.xsd`), co pozwala wykryć błędy strukturalne przed wysyłką do KSeF.

To oznacza, że akceptacja faktury nie tylko zmienia status w systemie, ale uruchamia też dalszy asynchroniczny workflow integracyjny.

### 5. Integracja z KSeF

Aplikacja obsługuje dwa tryby pracy integracji:

- `mock`, przeznaczony do developmentu lokalnego
- `live`, korzystający z rzeczywistego klienta KSeF

Obecny workflow integracyjny obejmuje:

- pobranie najnowszego payloadu XML faktury
- wysłanie dokumentu do KSeF
- zapis numeru referencyjnego i identyfikatorów sesji
- w trybie `mock` automatyczne zaakceptowanie faktury i nadanie numeru KSeF
- w trybie `live` utworzenie kolejnego zadania `POLL_KSEF_STATUS`
- cykliczne odpytywanie o wynik przetwarzania dokumentu
- oznaczenie dokumentu jako `ACCEPTED` albo `REJECTED`
- zapis eventów integracyjnych i payloadów odpowiedzi

W praktyce aplikacja utrzymuje pełny ślad techniczny procesu od zatwierdzenia dokumentu do uzyskania statusu końcowego w KSeF.

### 6. Obsługa faktur zakupowych

Faktury zakupowe są obsługiwane osobnym obszarem API i UI.

Aktualnie dostępne funkcje to:

- listowanie faktur zakupowych
- pobieranie szczegółów wyłącznie dla dokumentów typu `PURCHASE`
- kwalifikowanie faktury zakupowej do wysłania do biura księgowego
- odrzucanie faktury z procesu kosztowego
- pobieranie faktur zakupowych z API KSeF dla wskazanego zakresu dat (`POST /api/purchase-invoices/fetch-from-ksef`)
- import pojedynczego pliku XML FA(3) jako faktura zakupowa (`python scripts/import_purchase_xml.py <plik>`)

Endpoint `fetch-from-ksef` przyjmuje parametry `date_from` i `date_to` (ISO datetime) i zwraca liczbę zaimportowanych dokumentów wraz z ich identyfikatorami. Import deduplikuje faktury na podstawie `ksef_number` i `invoice_number`.

Parser XML rozpoznaje strukturę FA(3) v1-0E, w tym strony dokumentu (Podmiot1 = SELLER, Podmiot2 = BUYER) oraz pozycje z kodami VAT (23, 22, 8, 7, 5, 4, 3, 0, zw, oo, np, oss).

Kwalifikacja faktury zakupowej wpływa na pola i statusy robocze, między innymi:

- `accounting_qualified`
- `accounting_status`
- `accounting_notes`
- `review_status`
- `erp_status`

Pozytywna kwalifikacja ustawia dokument jako gotowy do wysłania do biura księgowego w ramach batcha miesięcznego. Negatywna kwalifikacja blokuje dokument i oznacza go jako odrzucony.

### 7. Batchowanie i wysyłka do biura księgowego

Aplikacja posiada wydzielony moduł przygotowania dokumentów do wysyłki do zewnętrznego biura księgowego.

Dostępne możliwości:

- kwalifikacja faktury do wysyłki (`POST /api/invoices/{id}/qualify`)
- dodanie pojedynczej faktury do batcha miesięcznego (`POST /api/invoices/{id}/add-to-batch`)
- generowanie miesięcznych batchy dla zakwalifikowanych faktur (sprzedażowych i zakupowych)
- listowanie batchy
- pobieranie szczegółów batcha
- usuwanie faktury z batcha (przed wysyłką)

Obsługiwane statusy procesu (`accounting_status`):

- `new` — nowa faktura, nie podjęto decyzji
- `qualified` — zakwalifikowana do wysyłki do biura
- `batched` — dodana do batcha miesięcznego
- `sent_to_office` — batch z tą fakturą został wysłany do biura księgowego
- `rejected` — odrzucona z procesu kosztowego

Generowanie batcha miesięcznego powoduje:

- wybór zakwalifikowanych faktur bez przypisanego batcha
- przypisanie ich do nowego lub istniejącego batcha dla danego okresu
- zmianę statusu dokumentów na `batched`
- utworzenie zadania `SEND_ACCOUNTING_BATCH`

Po wysłaniu batcha do biura księgowego:

- status batcha zmienia się na `SENT`
- statusy wszystkich faktur w batchu zmieniają się na `sent_to_office`
- biuro księgowe otrzymuje powiadomienie i może zaksięgować dokumenty w swoich systemach

### 8. Powiadomienia

System posiada moduł powiadomień oparty o log zdarzeń i wysyłkę e-mail lub Slack.

Aktualnie wspierane funkcje:

- utworzenie powiadomienia dla faktury
- ręczne wysłanie wskazanego powiadomienia
- listowanie historii powiadomień
- automatyczne tworzenie powiadomień po wysłaniu batcha do biura księgowego

Kanały wysyłki:

- **E-mail** (`EmailNotificationAdapter`) — obsługa SMTP z automatycznym rozpoznawaniem trybu szyfrowania: port 465 (implicit TLS/SMTPS), port 587 (STARTTLS), port 25 (plain z upgrade do TLS)
- **Slack** (`SlackNotificationAdapter`) — integracja z kanałami Slack

Powiadomienia zawierają co najmniej:

- numer faktury
- numer KSeF
- link do szczegółów faktury w UI
- referencję do payloadu XML

Status powiadomień i dokumentów jest aktualizowany po wysyłce lub błędzie wysyłki. System zapisuje też eventy `NOTIFICATION_CREATED`, `NOTIFICATION_SENT` oraz `NOTIFICATION_FAILED`.

### 9. Zarządzanie użytkownikami i rolami

Moduł użytkowników pozwala na administracyjne zarządzanie kontami aplikacyjnymi.

Obejmuje to:

- listowanie użytkowników wraz z przypisanymi rolami
- tworzenie nowych użytkowników lokalnych
- listowanie ról dostępnych w systemie
- nadawanie zestawu ról wybranemu użytkownikowi

Podczas tworzenia i aktualizacji ról system:

- normalizuje login użytkownika
- odrzuca próby utworzenia duplikatu loginu
- hashuje hasło lokalnego użytkownika
- odrzuca nieznane kody ról zamiast ich cichego ignorowania

### 10. Endpointy pomocnicze dla trybu agentowego

System udostępnia osobny zestaw endpointów pomocniczych dla użytkowników z rolą `admin` lub `agent`.

Obecnie obejmują one:

- endpoint zdrowia trybu agentowego
- podgląd kolejki zadań w statusach `NEW` i `PROCESSING`
- listę draftów o statusie ERP `DRAFT_CREATED`

Te endpointy są przydatne przy budowie agentów operacyjnych, paneli pomocniczych albo automatyzacji back-office.

### 11. Zdarzenia, payloady i ślad audytowy procesu

Aplikacja utrzymuje rozbudowany ślad zmian operacyjnych i integracyjnych. Dla dokumentów zapisywane są między innymi:

- eventy biznesowe, na przykład utworzenie, aktualizacja, akceptacja, kwalifikacja księgowa, dodanie do batcha
- eventy integracyjne, na przykład wysyłka do KSeF, akceptacja, odrzucenie, tworzenie i wysyłka powiadomień
- payloady XML i JSON związane z integracją
- znaczniki czasu dla etapów workflow
- informacje o aktorze, który wykonał operację

To pozwala analizować historię dokumentu zarówno z perspektywy biznesowej, jak i technicznej.

### 12. Przetwarzanie asynchroniczne i harmonogram

Aplikacja posiada dwa sposoby uruchamiania obsługi zadań w tle:

- **Scheduler** (klasa `Scheduler` w `app/workers/scheduler.py`) — główny proces przetwarzający, oparty o APScheduler, cyklicznie pobierający i obsługujący zadania z bazy w konfigurowalnym interwale (`SCHEDULER_INTERVAL`, domyślnie 180 sekund)
- **job_worker** (`app/workers/job_worker.py`) — shim kompatybilności wstecznej, reeksportujący klasę `Scheduler`

Obsługiwane typy zadań obejmują obecnie:

- `SEND_TO_KSEF`
- `POLL_KSEF_STATUS`
- `SEND_BOOKED_NOTIFICATION` (legacy, nie tworzony w nowych procesach)
- `SEND_ACCOUNTING_BATCH`
- `FETCH_KSEF_PURCHASES`

Mechanizm przetwarzania:

- Scheduler pobiera zadania o statusie `NEW` z blokadą na poziomie wiersza (`skip_locked`), co pozwala na bezpieczne uruchamianie wielu instancji
- oznacza zadania jako `PROCESSING` z metadanymi blokady roboczej
- kończy zadanie statusem `DONE` albo `FAILED`
- retry z wykładniczym backoffem: `delay = min(300, 5 × 2^(attempts−1))`
- monitorowanie heartbeat: Scheduler zapisuje w tabeli `worker_heartbeat` bieżący stan (faza: `idle`/`processing`/`cooldown`), ID i typ aktualnie przetwarzanego zadania oraz listę bieżących zadań w formacie JSON dla UI
- stale śledzone sekundy: `SCHEDULER_STALE_SECONDS` kontroluje próg uznania workera za nieaktywnego

### 13. Endpointy systemowe i developerskie

Poza główną logiką biznesową aplikacja udostępnia także:

- `/health` do prostego sprawdzenia dostępności aplikacji
- `/docs` z dokumentacją Swagger generowaną przez FastAPI
- `/api/me` do pobrania danych bieżącego użytkownika i jego ról
- `/static` do serwowania zasobów statycznych interfejsu WWW

### 14. Najważniejszy przebieg end-to-end

Najważniejszy obecnie scenariusz działania aplikacji wygląda tak:

1. Właściciel tworzy draft faktury sprzedażowej.
2. System wylicza sumy, zapisuje strony i pozycje oraz dodaje event utworzenia.
3. Właściciel waliduje i akceptuje fakturę.
4. System generuje XML, zapisuje payload, ustawia statusy i dodaje zadanie `SEND_TO_KSEF`.
5. Worker lub scheduler przetwarza zadanie integracyjne.
6. W trybie `mock` faktura otrzymuje numer KSeF od razu, a w trybie `live` system przechodzi przez polling statusu.
7. Po otrzymaniu numeru KSeF faktura sprzedażowa jest zakwalifikowana do wysyłki do biura księgowego.
8. Na koniec miesiąca właściciel generuje batch — wszystkie zakwalifikowane faktury trafiają do jednej paczki wysyłanej do biura.

Drugi kluczowy scenariusz — import i kwalifikacja faktur zakupowych:

1. Właściciel lub harmonogram wywołuje pobranie faktur z KSeF API dla zakresu dat.
2. System pobiera dokumenty XML z KSeF i parsuje je zgodnie ze schematem FA(3) v1-0E.
3. Każdy dokument jest deduplikowany po `ksef_number` i `invoice_number`.
4. Nowe faktury zakupowe są tworzone z pełną strukturą (strony, pozycje, sumy VAT) i statusem `ACCEPTED`.
5. Właściciel przegląda faktury zakupowe i kwalifikuje je do wysłania do biura lub odrzuca.
6. Zakwalifikowane faktury trafiają do batcha miesięcznego i są wysyłane do biura księgowego.


## Instalacja i konfiguracja
## Założenia

- Python 3.12 lub nowszy jest zainstalowany lokalnie.
- MySQL 8.0+ działa lokalnie (lub w kontenerze Docker) i jest dostępny na `localhost:3306` lub w innym skonfigurowanym porcie.
  - Serwer MySQL musi być uruchomiony i dostępny z poziomu administratora (`root` lub innego użytkownika z uprawnieniami tworzenia baz i użytkowników).
  - Serwer powinien obsługiwać kodowanie `utf8mb4` i zestaw znaków `utf8mb4_unicode_ci`.
- Pracujesz z katalogu repozytorium, a aplikacja znajduje się w folderze `ksef_app`.
- Git jest zainstalowany (opcjonalnie, jeśli klonujesz repozytorium).

## Krok 1. Przejdź do katalogu aplikacji

Ten krok ustawia bieżący katalog roboczy na folder aplikacji. Kolejne polecenia zakładają, że uruchamiasz je właśnie z `ksef_app`, ponieważ tam znajdują się `requirements.txt`, `.env.example`, skrypty inicjalizacyjne i główny moduł aplikacji.

```bash
cd ksef_app
```

## Krok 2. Utwórz i aktywuj środowisko wirtualne

Ten krok tworzy odseparowane środowisko Pythona dla projektu. Dzięki temu zależności aplikacji nie mieszają się z pakietami zainstalowanymi globalnie w systemie ani z innymi projektami.

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## Krok 3. Zainstaluj zależności

Ten krok instaluje wszystkie biblioteki wymagane przez aplikację, między innymi FastAPI, SQLAlchemy, Uvicorn, APScheduler i sterownik MySQL. Bez tego aplikacja i skrypty inicjalizacyjne nie uruchomią się poprawnie.

Windows i macOS:

```bash
python3 -m pip install --upgrade pip
pip install -r requirements.txt
```

## Krok 4. Utwórz bazę danych i użytkownika

Ten krok przygotowuje dostęp do bazy danych, z której korzysta aplikacja. Tworzysz pustą bazę `ksef_erp`, zakładasz użytkownika technicznego i nadajesz mu uprawnienia potrzebne do tworzenia tabel oraz późniejszej pracy aplikacji. Tabele i schemat zostaną utworzone automatycznie w kolejnym kroku przez migracje Alembic.

Połącz się z serwerem MySQL działającym lokalnie lub w kontenerze Docker i wykonaj poniższy blok SQL jako użytkownik administracyjny, na przykład `root`.

```sql
CREATE DATABASE IF NOT EXISTS ksef_erp
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'ksef_user'@'%' IDENTIFIED BY 'change_me'; -- ZMIEŃ to hasło przed uruchomieniem w sieci!

GRANT ALL PRIVILEGES ON ksef_erp.* TO 'ksef_user'@'%';

FLUSH PRIVILEGES;
```

Jeżeli MySQL działający w kontenerze Docker publikuje port `3306` na hosta, możesz wykonać blok SQL z klienta MySQL na hoście. Alternatywnie wejdź do kontenera i uruchom polecenie MySQL:

```bash
docker exec -it <nazwa_kontenera_mysql> mysql -uroot -p
```

Jeżeli MySQL jest zainstalowany lokalnie:

```bash
mysql -u root -p
```

Po wpisaniu hasła root będziesz w powłoce MySQL i możesz wkleić powyższy blok SQL.

## Krok 4.1. ~~Alternatywa: Kompletny skrypt SQL~~ — nie używaj

> **Uwaga:** Poniższy blok SQL jest przestarzały i **niezgodny z modelami SQLAlchemy** aplikacji (używa `BIGINT UNSIGNED` zamiast `INTEGER`). Nie wykonuj go. Schemat bazy twórz wyłącznie przez `python scripts/create_tables.py` (Krok 7).

```sql
USE mysql;
CREATE DATABASE IF NOT EXISTS ksef_erp CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'ksef_user'@'%' IDENTIFIED BY 'change_me';
GRANT ALL PRIVILEGES ON ksef_erp.* TO 'ksef_user'@'%';
FLUSH PRIVILEGES;

USE ksef_erp;

CREATE TABLE app_user (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_uuid CHAR(36) NOT NULL,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255) NULL,
    display_name VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    auth_provider VARCHAR(50) NOT NULL DEFAULT 'LOCAL' COMMENT 'LOCAL / ENTRA',
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    is_locked TINYINT(1) NOT NULL DEFAULT 0,
    last_login_at DATETIME NULL,
    metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_app_user_uuid (user_uuid),
    UNIQUE KEY uq_app_user_username (username),
    UNIQUE KEY uq_app_user_email (email),
    CHECK (metadata IS NULL OR JSON_VALID(metadata))
) ENGINE=InnoDB;

CREATE TABLE app_role (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    role_code VARCHAR(50) NOT NULL,
    role_name VARCHAR(100) NOT NULL,
    description VARCHAR(500) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_app_role_code (role_code)
) ENGINE=InnoDB;

CREATE TABLE app_user_role (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id BIGINT UNSIGNED NOT NULL,
    role_id BIGINT UNSIGNED NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_app_user_role (user_id, role_id),
    KEY idx_app_user_role_role_id (role_id),
    CONSTRAINT fk_app_user_role_user
        FOREIGN KEY (user_id) REFERENCES app_user(id) ON DELETE CASCADE,
    CONSTRAINT fk_app_user_role_role
        FOREIGN KEY (role_id) REFERENCES app_role(id) ON DELETE CASCADE
) ENGINE=InnoDB;

INSERT INTO app_role (role_code, role_name, description) VALUES
('admin', 'Administrator', 'Pełne uprawnienia administracyjne'),
('agent', 'Agent AI', 'Tworzenie draftów i operacje automatyczne bez akceptacji'),
('reviewer', 'Reviewer', 'Edycja i akceptacja dokumentów'),
('owner', 'Właściciel/Operator', 'Wystawianie faktur, kwalifikacja zakupów, zarządzanie batchami do biura księgowego'),
('viewer', 'Viewer', 'Dostęp tylko do odczytu');

CREATE TABLE party (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    party_uuid CHAR(36) NOT NULL,
    party_name VARCHAR(255) NOT NULL,
    tax_id VARCHAR(20) NULL,
    country_code VARCHAR(2) NULL,
    street_address VARCHAR(255) NULL,
    city VARCHAR(100) NULL,
    postal_code VARCHAR(20) NULL,
    email VARCHAR(255) NULL,
    phone VARCHAR(20) NULL,
    metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_party_uuid (party_uuid),
    KEY idx_party_tax_id (tax_id)
) ENGINE=InnoDB;

CREATE TABLE dicts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    dict_name VARCHAR(100) NOT NULL,
    dict_code VARCHAR(100) NOT NULL,
    dict_value VARCHAR(255) NOT NULL,
    dict_description VARCHAR(500) NULL,
    sort_order INT DEFAULT 0,
    is_active TINYINT(1) NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_dict_code (dict_name, dict_code),
    KEY idx_dict_name (dict_name)
) ENGINE=InnoDB;

CREATE TABLE ksef_session (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    session_uuid CHAR(36) NOT NULL,
    session_token VARCHAR(255) NULL,
    reference_number VARCHAR(100) NULL,
    status VARCHAR(50) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uq_ksef_session_uuid (session_uuid),
    KEY idx_ksef_session_status (status)
) ENGINE=InnoDB;

CREATE TABLE invoice (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_uuid CHAR(36) NOT NULL,
    invoice_number VARCHAR(100) NOT NULL,
    direction_code VARCHAR(50) NOT NULL COMMENT 'SALE / PURCHASE',
    invoice_type VARCHAR(50) NULL,
    ksef_status_code VARCHAR(50) NULL COMMENT 'KSeF workflow status',
    erp_status VARCHAR(50) NULL COMMENT 'ERP workflow status',
    review_status VARCHAR(50) NULL COMMENT 'Review status: PENDING / APPROVED / REJECTED',
    accounting_status VARCHAR(50) NULL COMMENT 'Accounting status: new / qualified / batched / sent_to_office / rejected',
    issue_date DATE NOT NULL,
    due_date DATE NULL,
    invoice_currency VARCHAR(3) DEFAULT 'PLN',
    total_netto DECIMAL(15,2) DEFAULT 0,
    total_vat DECIMAL(15,2) DEFAULT 0,
    total_gross DECIMAL(15,2) DEFAULT 0,
    ksef_number VARCHAR(50) NULL,
    ksef_hash VARCHAR(64) NULL,
    review_locked_by BIGINT UNSIGNED NULL,
    review_locked_at DATETIME NULL,
    approved_by BIGINT UNSIGNED NULL,
    approved_at DATETIME NULL,
    accounting_marked_by BIGINT UNSIGNED NULL,
    accounting_marked_at DATETIME NULL,
    accounting_notes TEXT NULL,
    accounting_qualified TINYINT(1) NULL DEFAULT 0,
    accounting_batch_id VARCHAR(100) NULL,
    notification_status VARCHAR(50) NULL COMMENT 'PENDING / SENT / FAILED / SKIPPED',
    notification_channel VARCHAR(50) NULL COMMENT 'EMAIL / SLACK / NONE',
    last_notification_at DATETIME NULL,
    created_by BIGINT UNSIGNED NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_invoice_uuid (invoice_uuid),
    KEY idx_invoice_number (invoice_number),
    KEY idx_invoice_direction (direction_code),
    KEY idx_invoice_ksef_status (ksef_status_code),
    KEY idx_invoice_erp_status (erp_status),
    KEY idx_invoice_review_status (review_status),
    KEY idx_invoice_accounting_status (accounting_status),
    KEY idx_invoice_approved_by (approved_by),
    KEY idx_invoice_accounting_qualified (accounting_qualified),
    CONSTRAINT fk_invoice_review_locked_by FOREIGN KEY (review_locked_by) REFERENCES app_user(id) ON DELETE SET NULL,
    CONSTRAINT fk_invoice_approved_by FOREIGN KEY (approved_by) REFERENCES app_user(id) ON DELETE SET NULL,
    CONSTRAINT fk_invoice_accounting_marked_by FOREIGN KEY (accounting_marked_by) REFERENCES app_user(id) ON DELETE SET NULL,
    CONSTRAINT fk_invoice_created_by FOREIGN KEY (created_by) REFERENCES app_user(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE invoice_party (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    party_id BIGINT UNSIGNED NULL,
    party_role VARCHAR(50) NOT NULL COMMENT 'SELLER / BUYER / ISSUER / RECIPIENT',
    party_name VARCHAR(255) NOT NULL,
    tax_id VARCHAR(20) NULL,
    country_code VARCHAR(2) NULL,
    street_address VARCHAR(255) NULL,
    city VARCHAR(100) NULL,
    postal_code VARCHAR(20) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_invoice_party_invoice (invoice_id),
    CONSTRAINT fk_invoice_party_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_line (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    line_number INT NOT NULL,
    description VARCHAR(500) NOT NULL,
    quantity DECIMAL(15,2) NOT NULL,
    unit_price DECIMAL(15,2) NOT NULL,
    net_amount DECIMAL(15,2) NOT NULL,
    vat_rate DECIMAL(5,2) NOT NULL,
    vat_code VARCHAR(50) NULL,
    reverse_charge TINYINT(1) NOT NULL DEFAULT 0,
    tax_procedure_code VARCHAR(50) NULL,
    tax_exemption_reason VARCHAR(255) NULL,
    vat_amount DECIMAL(15,2) NOT NULL,
    gross_amount DECIMAL(15,2) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_invoice_line_invoice (invoice_id),
    KEY idx_invoice_line_reverse_charge (reverse_charge),
    KEY idx_invoice_line_vat_code (vat_code),
    CONSTRAINT fk_invoice_line_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_payment (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    payment_method VARCHAR(50) NULL,
    payment_term_days INT NULL,
    bank_account VARCHAR(50) NULL,
    swift_code VARCHAR(20) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_invoice_payment_invoice (invoice_id),
    CONSTRAINT fk_invoice_payment_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_vat_summary (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    vat_rate DECIMAL(5,2) NOT NULL,
    vat_code VARCHAR(50) NULL,
    net_amount DECIMAL(15,2) NOT NULL,
    vat_amount DECIMAL(15,2) NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_invoice_vat_summary_invoice (invoice_id),
    CONSTRAINT fk_invoice_vat_summary_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_relation (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    related_invoice_id BIGINT UNSIGNED NULL,
    relation_type VARCHAR(50) NULL COMMENT 'CORRECTION_OF / CORRECTED_BY / REFERENCE_TO',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY idx_invoice_relation_invoice (invoice_id),
    CONSTRAINT fk_invoice_relation_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_attachment (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    attachment_uuid CHAR(36) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    file_size BIGINT NOT NULL,
    mime_type VARCHAR(100) NULL,
    file_hash VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_invoice_attachment_uuid (attachment_uuid),
    KEY idx_invoice_attachment_invoice (invoice_id),
    CONSTRAINT fk_invoice_attachment_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_payload (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    payload_uuid CHAR(36) NOT NULL,
    payload_type VARCHAR(100) NOT NULL COMMENT 'KSEF_XML / KSEF_RESPONSE / etc',
    payload_data LONGTEXT NOT NULL,
    payload_hash VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_invoice_payload_uuid (payload_uuid),
    KEY idx_invoice_payload_invoice (invoice_id),
    KEY idx_invoice_payload_type (payload_type),
    CONSTRAINT fk_invoice_payload_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE invoice_event (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    invoice_id BIGINT UNSIGNED NOT NULL,
    event_uuid CHAR(36) NOT NULL,
    event_type VARCHAR(100) NOT NULL COMMENT 'CREATED / UPDATED / APPROVED / SENT_TO_KSEF etc',
    event_description VARCHAR(500) NULL,
    event_actor_id BIGINT UNSIGNED NULL,
    event_metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_invoice_event_uuid (event_uuid),
    KEY idx_invoice_event_invoice (invoice_id),
    KEY idx_invoice_event_type (event_type),
    CONSTRAINT fk_invoice_event_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE integration_job (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    job_uuid CHAR(36) NOT NULL,
    job_type VARCHAR(100) NOT NULL COMMENT 'SEND_TO_KSEF / POLL_KSEF_STATUS / SEND_NOTIFICATION etc',
    status VARCHAR(50) NOT NULL COMMENT 'NEW / PROCESSING / DONE / FAILED',
    session_id BIGINT UNSIGNED NULL,
    related_entity_type VARCHAR(50) NULL COMMENT 'INVOICE / ACCOUNTING_BATCH / NOTIFICATION',
    related_entity_id VARCHAR(100) NULL,
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 3,
    last_error VARCHAR(1000) NULL,
    locked_by VARCHAR(100) NULL,
    locked_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_integration_job_uuid (job_uuid),
    KEY idx_integration_job_status (status),
    KEY idx_integration_job_type (job_type),
    KEY idx_integration_job_related_entity (related_entity_type, related_entity_id),
    KEY idx_integration_job_locked_at (locked_at),
    CONSTRAINT fk_integration_job_session FOREIGN KEY (session_id) REFERENCES ksef_session(id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE accounting_batch (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_uuid CHAR(36) NOT NULL,
    batch_code VARCHAR(100) NOT NULL,
    batch_type VARCHAR(50) NOT NULL COMMENT 'PURCHASE_MONTHLY',
    status VARCHAR(50) NOT NULL COMMENT 'NEW / GENERATED / SENT / FAILED / CLOSED',
    period_year INT NOT NULL,
    period_month INT NOT NULL,
    criteria_json JSON NULL,
    item_count INT NOT NULL DEFAULT 0,
    created_by BIGINT UNSIGNED NULL,
    approved_by BIGINT UNSIGNED NULL,
    sent_at DATETIME NULL,
    metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_accounting_batch_uuid (batch_uuid),
    UNIQUE KEY uq_accounting_batch_code (batch_code),
    KEY idx_accounting_batch_status (status),
    KEY idx_accounting_batch_period (period_year, period_month),
    CONSTRAINT fk_accounting_batch_created_by FOREIGN KEY (created_by) REFERENCES app_user(id) ON DELETE SET NULL,
    CONSTRAINT fk_accounting_batch_approved_by FOREIGN KEY (approved_by) REFERENCES app_user(id) ON DELETE SET NULL,
    CHECK (criteria_json IS NULL OR JSON_VALID(criteria_json)),
    CHECK (metadata IS NULL OR JSON_VALID(metadata))
) ENGINE=InnoDB;

CREATE TABLE accounting_batch_invoice (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    batch_id BIGINT UNSIGNED NOT NULL,
    invoice_id BIGINT UNSIGNED NOT NULL,
    inclusion_status VARCHAR(50) NOT NULL COMMENT 'SELECTED / SENT / SKIPPED / REJECTED',
    inclusion_reason VARCHAR(1000) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_accounting_batch_invoice (batch_id, invoice_id),
    KEY idx_accounting_batch_invoice_invoice_id (invoice_id),
    CONSTRAINT fk_accounting_batch_invoice_batch FOREIGN KEY (batch_id) REFERENCES accounting_batch(id) ON DELETE CASCADE,
    CONSTRAINT fk_accounting_batch_invoice_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE notification_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    notification_uuid CHAR(36) NOT NULL,
    invoice_id BIGINT UNSIGNED NULL,
    batch_id BIGINT UNSIGNED NULL,
    channel VARCHAR(50) NOT NULL COMMENT 'EMAIL / SLACK',
    recipient VARCHAR(255) NOT NULL,
    subject VARCHAR(500) NULL,
    payload JSON NULL,
    status VARCHAR(50) NOT NULL COMMENT 'NEW / SENT / FAILED',
    error_message VARCHAR(2000) NULL,
    sent_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_notification_log_uuid (notification_uuid),
    KEY idx_notification_log_invoice_id (invoice_id),
    KEY idx_notification_log_batch_id (batch_id),
    KEY idx_notification_log_status (status),
    CONSTRAINT fk_notification_log_invoice FOREIGN KEY (invoice_id) REFERENCES invoice(id) ON DELETE SET NULL,
    CONSTRAINT fk_notification_log_batch FOREIGN KEY (batch_id) REFERENCES accounting_batch(id) ON DELETE SET NULL,
    CHECK (payload IS NULL OR JSON_VALID(payload))
) ENGINE=InnoDB;
```

Powtarzamy: **nie uruchamiaj tego SQL**. Służy tylko jako dokumentacja historyczna.

## Krok 5. Utwórz plik konfiguracyjny `.env`

Ten krok tworzy lokalny plik konfiguracyjny na podstawie szablonu. Aplikacja odczytuje z niego ustawienia połączenia z bazą, dane administratora, parametry serwera i konfigurację integracji.

Windows (PowerShell):

```powershell
Copy-Item .env.example .env
```

macOS:

```bash
cp .env.example .env
```

## Krok 6. Uzupełnij konfigurację w `.env`

Ten krok dostosowuje aplikację do lokalnego środowiska. Najważniejsze są dane połączenia z MySQL, bezpieczny `SECRET_KEY` oraz `ADMIN_DEFAULT_PASSWORD`, z którego skorzysta później skrypt tworzący konto administratora.

Ustaw co najmniej poniższe wartości:

```env
APP_HOST=127.0.0.1
APP_PORT=8000
BASE_URL=http://127.0.0.1:8000

DB_HOST=127.0.0.1
DB_PORT=3306
DB_NAME=ksef_erp
DB_USER=ksef_user
DB_PASSWORD=change_me   # WYMAGANE: ustaw silne, unikalne hasło — nigdy nie używaj tej wartości w produkcji

BASIC_AUTH_REALM=KSeF ERP
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

# Worker tuning (opcjonalne)
WORKER_POLL_INTERVAL=5    # opóźnienie bezczynnego job_worker między sprawdzeniami kolejki (sekundy)
SCHEDULER_INTERVAL=10     # interwał schedulera APScheduler (sekundy)
SCHEDULER_STALE_SECONDS=600  # próg uznania workera za nieaktywnego (sekundy)
UI_SESSION_MAX_AGE=43200  # czas życia sesji UI w sekundach (domyślnie 12h)

ADMIN_DEFAULT_PASSWORD=<haslo_dla_uzytkownika_admin>
```

Losowy klucz do `SECRET_KEY` możesz wygenerować tak:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```


## Krok 7. Utwórz lub zaktualizuj schemat bazy

Ten krok przygotowuje strukturę bazy danych przed załadowaniem słowników i utworzeniem użytkownika administratora. Migracje Alembic tworzą kompletny schemat zawierający wszystkie tabele i rozszerzenia niezbędne do pracy aplikacji.

### Tabele tworzone przez migracje

Migracje tworzą lub rozszerzają następujące komponenty bazy:

**Tabele użytkowników i ról:**
- `app_user` — rejestr użytkowników aplikacji z haszami haseł, statusami blokady i metadanymi
- `app_role` — słownik dostępnych ról systemowych (`admin`, `agent`, `reviewer`, `owner`, `viewer`)
- `app_user_role` — powiązania użytkowników z rolami

**Tabele dokumentów i faktur:**
- `invoice` — główny rejestr faktur z rozszerzeniami o:
  - statusy review i akceptacji (`review_status`, `approved_by`, `approved_at`)
  - statusy księgowe i kwalifikację (`accounting_status`, `accounting_qualified`, `accounting_batch_id`)
  - ślady zmian (`review_locked_by`, `accounting_marked_by`)
  - powiadomienia (`notification_status`, `notification_channel`, `last_notification_at`)
- `invoice_line` — pozycje faktur z dodatkowymi polami podatkowymi:
  - `reverse_charge` — flaga reverse charge
  - `tax_procedure_code` — kod procedury podatkowej
  - `tax_exemption_reason` — przyczyna zwolnienia
- `invoice_party`, `invoice_payload`, `invoice_event`, `invoice_payment`, `invoice_relation`, `invoice_vat_summary`, `invoice_attachment` — tabele wspierające pełną strukturę dokumentu

**Tabele integracji i zadań:**
- `integration_job` — kolejka zadań integracyjnych z rozszerzeniami o:
  - powiązanie z jednostkami (`related_entity_type`, `related_entity_id`)
  - blokady robocze (`locked_by`, `locked_at`)
- `ksef_session` — sesje integracyjne z systemem KSeF
- `ksef_session_invoice` — powiązanie faktur z sesjami KSeF (kody przetwarzania, referencje batchowe)

**Tabele procesów księgowych i powiadomień:**
- `accounting_batch` — okresy zbiorcze dla batch processing (np. faktury zakupowe miesięczne)
- `accounting_batch_invoice` — powiązanie faktur z batchami księgowymi
- `notification_log` — rejestr wszystkich wysyłanych powiadomień (e-mail, Slack) z statusami i payload'ami

**Tabele monitorowania:**
- `worker_heartbeat` — monitorowanie stanu workerów z fazami (`idle`/`processing`/`cooldown`), bieżącym zadaniem i listą zadań JSON dla UI

**Tabele słownikowe:**
- `party` — słownik stron dokumentów
- `dicts` — rejestr słowników systemowych (kierunki, typy, statusy, role stron)

### Nowa baza (pierwsze uruchomienie)

Dla pustej bazy utwórz schemat bezpośrednio ze skryptu inicjalizacyjnego, który odczytuje modele SQLAlchemy:

```bash
python3 scripts/create_tables.py
```

Następnie oznacz wszystkie migracje jako zastosowane (nie uruchamiaj ich — tabele już istnieją):

```bash
alembic stamp head
```

### Aktualizacja istniejącej bazy

Dla bazy utworzonej wcześniej przez `create_tables.py`, przy aktualizacji kodu uruchom:

```bash
alembic upgrade head
```

> **Ważne:** Nie używaj `alembic upgrade head` na nowej, pustej bazie. Migracje zakładają, że podstawowy schemat został już utworzony przez `create_tables.py`.

## Krok 8. Załaduj dane słownikowe

Ten krok wypełnia bazę danymi referencyjnymi, z których aplikacja korzysta od razu po starcie. Skrypt dodaje brakujące słowniki i role systemowe, między innymi:

- kierunki faktur, na przykład `SALE` i `PURCHASE`
- typy faktur, na przykład `STANDARD`, `CORRECTION`, `ADVANCE`
- role stron dokumentu, na przykład `SELLER`, `BUYER`, `ISSUER`, `RECIPIENT`
- statusy obiegu KSeF, na przykład `DRAFT`, `SENT`, `ACCEPTED`, `ERROR`
- typy payloadów integracyjnych
- role użytkowników, na przykład `admin`, `agent`, `reviewer`, `owner`, `viewer`

Skrypt nie powinien duplikować istniejących wpisów, więc można go uruchomić bezpiecznie także wtedy, gdy część danych została już wcześniej dodana.

```bash
python3 scripts/seed_reference_data.py
```

## Krok 9. Utwórz konto administratora

Ten krok tworzy lokalne konto administracyjne, którego możesz użyć do pierwszego logowania do aplikacji. Skrypt:

- sprawdza, czy użytkownik `admin` już istnieje
- tworzy użytkownika `admin` z adresem `admin@ksef.local`
- hashuje hasło pobrane z `ADMIN_DEFAULT_PASSWORD` w pliku `.env`
- przypisuje rolę `admin`, jeżeli została wcześniej załadowana do bazy

Skrypt nie nadpisuje istniejącego konta `admin`. Jeżeli taki użytkownik jest już w bazie, zakończy działanie bez tworzenia duplikatu.

Przed uruchomieniem tego kroku upewnij się, że w `.env` ustawiono `ADMIN_DEFAULT_PASSWORD`.

```bash
python3 scripts/create_admin.py
```

Po wykonaniu skryptu zostanie utworzony użytkownik `admin` z hasłem z pola `ADMIN_DEFAULT_PASSWORD`.

## Krok 10. Uruchom aplikację

Ten krok startuje serwer HTTP aplikacji przez Uvicorn i ładuje obiekt `app` z modułu `main.py`. Flaga `--reload` włącza automatyczne przeładowanie po zmianach w kodzie, więc ten tryb jest przeznaczony do pracy lokalnej i developmentu.

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

## Krok 11. Otwórz aplikację w przeglądarce

Po uruchomieniu serwera możesz sprawdzić trzy podstawowe adresy: interfejs użytkownika, dokumentację API i endpoint kontrolny potwierdzający, że aplikacja odpowiada.

- UI: `http://127.0.0.1:8000/ui`
- Swagger: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Krok 12. Opcjonalnie uruchom procesy pomocnicze

Te procesy nie są wymagane do samego uruchomienia interfejsu WWW, ale są potrzebne, jeśli chcesz obsługiwać zadania asynchroniczne w tle.

Worker kolejek:

Ten proces działa w pętli i pobiera z bazy kolejne zadania integracyjne ze statusem `NEW`. Obsługuje między innymi wysyłkę do KSeF, odpytywanie o status KSeF, import faktur zakupowych oraz wysyłkę powiadomień. Gdy kolejka jest pusta, czeka `WORKER_POLL_INTERVAL` sekund (domyślnie 5) przed kolejnym sprawdzeniem.

> **Uwaga:** `job_worker.py` jest shimem kompatybilności wstecznej — reeksportuje klasę `Scheduler`. Zalecany sposób uruchamiania to przez moduł schedulera.

```bash
python3 -m app.workers.job_worker
```

Scheduler:

Ten proces uruchamia harmonogram APScheduler, który cyklicznie wywołuje przetwarzanie kolejki zadań. Wykorzystuje blokadę wierszy (`skip_locked`), co pozwala na bezpieczne uruchamianie wielu instancji. Interwał kontrolowany jest przez `SCHEDULER_INTERVAL` (domyślnie 10 sekund). Scheduler zapisuje heartbeat do bazy danych, co umożliwia monitorowanie stanu workera z poziomu UI.

```bash
python3 -m app.workers.scheduler
```

## Krok 13. Przełącz na tryb live (opcjonalnie)

Domyślnie aplikacja działa w trybie `mock` — faktura jest akceptowana natychmiast lokalnie, bez kontaktu z serwerami MF. Aby podłączyć rzeczywisty KSeF, wykonaj poniższe kroki.

### Wymagania wstępne

- Token autoryzacyjny KSeF (`ksef_token`) dla twojego NIP-u.
- NIP podmiotu autoryzującego.

### Zmiana konfiguracji `.env`

Ustaw następujące wartości w pliku `.env`:

```env
KSEF_MODE=live

KSEF_API_URL=https://api.ksef.mf.gov.pl/v2   # produkcja; dla środowiska testowego: https://api.test.ksef.mf.gov.pl/v2
KSEF_TOKEN=<twój_token_ksef>
KSEF_NIP=<nip_podmiotu>
```

> **Uwaga:** Po zmianie `KSEF_MODE` na `live` zatwierdzone faktury są wysyłane do KSeF natychmiast przez workera. Upewnij się, że token i NIP są poprawne, zanim zaakceptujesz pierwszy dokument.

### Różnica w zachowaniu trybu live względem mock

| Aspekt | `mock` | `live` |
|---|---|---|
| Wysyłka XML | pominięta | HTTP POST do KSeF API |
| Numer KSeF | generowany lokalnie | nadawany przez MF |
| Polling statusu | pominięty | zadanie `POLL_KSEF_STATUS` w kolejce |
| Wymagany worker | tak | tak (polling nie działa bez workera) |

### Ponowne uruchomienie procesów

Po zmianie `.env` zrestartuj aplikację i workera, żeby odczytały nową konfigurację:

```bash
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

```bash
python3 -m app.workers.job_worker    
# lub
python3 -m app.workers.scheduler.  # uzywaj tego, on regularnie startuje job_workera
```

## Krok 14. Uruchom testy

Minimalny zestaw testów regresyjnych obejmuje walidację wyliczeń faktur, logikę retry workera oraz integralność nowych constraintów modelu.

```bash
python3 -m pytest tests
```

### Pokrycie testowe

Testy regresyjne znajdują się w katalogu `tests/` i obejmują:

| Plik | Zakres |
| --- | --- |
| `test_invoice_service.py` | Wyliczenia kwot linii faktur, rabatów i VAT (testy parametryzowane) |
| `test_ksef_import.py` | Parsowanie XML FA(3) v1-0E — numer faktury, daty, strony, pozycje, kody VAT |
| `test_job_worker.py` | Logika przetwarzania zadań w tle: claimowanie, przejścia statusów, retry |
| `test_schema_constraints.py` | Walidacja constraintów schematu bazy danych |
| `test_security_review.py` | Testy bezpieczeństwa aplikacji |

### Migracje Alembic

Migracje znajdują się w `alembic/versions/`:

| Migracja | Opis |
| --- | --- |
| `20260514_0001` | Dodanie CASCADE FK dla `invoice_party.party_id`, unique constraint dla batch invoice |
| `20260514_0002` | Utworzenie tabeli `notification_log`, dodanie `totp_secret` do `app_user` |
| `20260514_0003` | Utworzenie tabeli `worker_heartbeat` z indeksem na `worker_id` |
| `20260515_0001` | Dodanie unique constraint na `invoice.invoice_number` |
| `20260515_0002` | Dodanie kolumn `phase` i `current_jobs_json` do `worker_heartbeat` |
| `20260516_0001` | Zmiana roli `accountant` → `owner`, migracja statusów `accounting_status` i `erp_status` |

## Schemat bazy danych v1

Baza danych `ksef_erp` jest centralnym repozytorium dla całego systemu KSeF ERP. Po uruchomieniu migracji Alembic zawiera następujące komponenty:

### Zarządzanie dostępem

| Tabela | Zawartość |
| --- | --- |
| `app_user` | Konta użytkowników aplikacji z hasłami (bcrypt_sha256), statusami, metadanymi i opcjonalnym sekretem TOTP (`totp_secret`) |
| `app_role` | Role systemowe: `admin`, `agent`, `reviewer`, `owner`, `viewer` |
| `app_user_role` | Powiązania: które role mają konkretni użytkownicy |
| `worker_heartbeat` | Stan workerów: heartbeat, faza, bieżące zadania |

### Rejestry dokumentów

| Tabela | Zawartość |
| --- | --- |
| `invoice` | Główny rejestr faktur (sprzedażowych i zakupowych) z pełnym cyklem życia |
| `invoice_line` | Pozycje faktury z podatkami, VAT i kodami procedur podatkowych |
| `invoice_party` | Strony dokumentów: sprzedawca, nabywca, wystawca, odbiorca |
| `invoice_payment` | Informacje o płatności i warunkach płatności |
| `invoice_vat_summary` | Podsumowania VAT dla każdej stawki w dokumencie |
| `invoice_relation` | Powiązania między fakturami (np. korekta do oryginału) |
| `invoice_attachment` | Załączniki i pliki związane z fakturą |

### Integracja i workflow

| Tabela | Zawartość |
| --- | --- |
| `invoice_payload` | Payloady XML faktury i odpowiedzi z KSeF |
| `invoice_event` | Pełna historia zdarzeń: tworzenie, edycja, akceptacja, wysyłka, notyfikacje |
| `ksef_session` | Sesje integracyjne z systemem KSeF |
| `ksef_session_invoice` | Powiązanie faktur z sesjami KSeF (kody przetwarzania) |
| `integration_job` | Kolejka asynchronicznych zadań: wysyłka, polling, import, notyfikacje |

### Procesy księgowe

| Tabela | Zawartość |
| --- | --- |
| `accounting_batch` | Okresy zbiorcze dla batch processing (np. faktury zakupowe miesięczne) |
| `accounting_batch_invoice` | Fakty: które faktury należą do które batcha |
| `notification_log` | Historia wysyłania powiadomień (e-mail, Slack) z statusami |

### Monitorowanie

| Tabela | Zawartość |
| --- | --- |
| `worker_heartbeat` | Stan workerów: heartbeat, faza (idle/processing/cooldown), bieżące zadania JSON |

### Słowniki referencyjne

| Tabela | Zawartość |
| --- | --- |
| `party` | Słownik stron: firmy, podmioty, adresy |
| `dicts` | Słowniki systemowe: kierunki faktur, typy, statusy KSeF, role stron |

### Statusy i przepływy

Dokumenty w systemie przechodzą przez kilka niezależnych wymiarów statusów:

- **`ksef_status_code`**: `DRAFT` → `GENERATED` → `QUEUED` → `SENT` → `PROCESSING` → `ACCEPTED`/`REJECTED`
- **`erp_status`**: `DRAFT_CREATED` → `READY_FOR_REVIEW` → `APPROVED` → `QUEUED_FOR_KSEF` → `SENT_TO_KSEF` → `KSEF_ACCEPTED` → `READY_FOR_ACCOUNTING` → `ACCOUNTING_BATCHED` → `SENT_TO_OFFICE`
- **`accounting_status`**: `new` → `qualified` → `batched` → `sent_to_office` / `rejected`
- **`review_status`**: `PENDING` → `APPROVED` / `REJECTED`

Te statusy są niezależne, co pozwala na elastyczne modelowanie złożonych procesów biznesowych.

### Klucze obce i spójność

Wszystkie tabele zawierają odpowiednie klucze obce (`FOREIGN KEY`), indeksy (`KEY`) i ograniczenia (`CHECK`), które zapewniają integralność danych. Operacje usuwania są zabezpieczone przez `ON DELETE CASCADE` lub `ON DELETE SET NULL` zależnie od semantyki powiązania.

## Skrócona kolejność działań

1. `cd ksef_app`
2. Utwórz i aktywuj `.venv` na Windows albo macOS
3. `pip install -r requirements.txt`
4. Wykonaj blok SQL tworzący bazę i użytkownika MySQL
5. Skopiuj `.env.example` do `.env`
6. Uzupełnij ustawienia bazy, `SECRET_KEY` i `ADMIN_DEFAULT_PASSWORD`
7. **Nowa baza:** `python scripts/create_tables.py` → `alembic stamp head` / **Aktualizacja:** `alembic upgrade head`
8. `python scripts/seed_reference_data.py`
9. `python scripts/create_admin.py`
10. `uvicorn main:app --reload --host 127.0.0.1 --port 8000`
