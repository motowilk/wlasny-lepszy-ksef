# Własny Lepszy KSeF

Poniżej znajduje się uproszczona instrukcja pierwszego uruchomienia projektu. Zawiera tylko kroki operacyjne potrzebne do startu aplikacji lokalnie, bez opisu architektury i bez zawartości plików źródłowych.

## Założenia

- Python 3.12 lub nowszy jest zainstalowany lokalnie.
- MySQL 8 działa w kontenerze Docker i jest wystawiony na `localhost:3306`.
- Pracujesz z katalogu repozytorium, a aplikacja znajduje się w folderze `ksef_app`.

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
python3.12 -m venv .venv
source .venv/bin/activate
```

## Krok 3. Zainstaluj zależności

Ten krok instaluje wszystkie biblioteki wymagane przez aplikację, między innymi FastAPI, SQLAlchemy, Uvicorn, APScheduler i sterownik MySQL. Bez tego aplikacja i skrypty inicjalizacyjne nie uruchomią się poprawnie.

Windows i macOS:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Krok 4. Utwórz bazę danych i użytkownika

Ten krok przygotowuje dostęp do bazy danych, z której korzysta aplikacja. Tworzysz pustą bazę `ksef_erp`, zakładasz użytkownika technicznego i nadajesz mu uprawnienia potrzebne do tworzenia tabel oraz późniejszej pracy aplikacji.

Połącz się z serwerem MySQL działającym w kontenerze Docker i wykonaj poniższy blok SQL jako użytkownik administracyjny, na przykład `root`.

```sql
CREATE DATABASE IF NOT EXISTS ksef_erp
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

CREATE USER IF NOT EXISTS 'ksef_user'@'%' IDENTIFIED BY 'change_me'; -- ZMIEŃ to hasło przed uruchomieniem w sieci!

GRANT ALL PRIVILEGES ON ksef_erp.* TO 'ksef_user'@'%';

FLUSH PRIVILEGES;
```

Jeżeli kontener publikuje port `3306` na hosta, możesz wykonać blok SQL z klienta MySQL na hoście albo wejść do kontenera poleceniem typu:

```bash
docker exec -it <nazwa_kontenera_mysql> mysql -uroot -p
```

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
DEFAULT_NOTIFICATION_EMAIL=accountant@example.com

LOG_LEVEL=INFO
LOG_DIR=logs

ADMIN_DEFAULT_PASSWORD=<haslo_dla_uzytkownika_admin>
```

Losowy klucz do `SECRET_KEY` możesz wygenerować tak:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Aktualna funkcjonalność aplikacji

Po skonfigurowaniu środowiska aplikacja udostępnia kompletny lokalny system do obsługi obiegu faktur w modelu KSeF ERP. Poniżej znajduje się opis aktualnych możliwości wynikających z bieżącego kodu aplikacji.

### 1. Model dostępu i uwierzytelnianie

- Aplikacja korzysta z HTTP Basic Auth dla API i interfejsu WWW.
- Logowanie odbywa się na kontach zapisanych w bazie danych, z hasłami przechowywanymi w postaci hashy bcrypt.
- Po poprawnym logowaniu aktualizowana jest data ostatniego logowania użytkownika.
- Dostęp do operacji jest ograniczany rolami systemowymi.
- Obsługiwane role obejmują co najmniej: `admin`, `agent`, `reviewer`, `accountant`, `viewer`.
- Konto `admin` jest tworzone skryptem inicjalizacyjnym na podstawie `ADMIN_DEFAULT_PASSWORD` z `.env`.

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

Z poziomu UI można obecnie:

- utworzyć nowy draft faktury sprzedażowej
- obejrzeć szczegóły faktury wraz z historią zdarzeń
- zaakceptować fakturę i przekazać ją do kolejki integracyjnej KSeF

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
- kwalifikowanie faktury zakupowej do procesu księgowego
- odrzucanie faktury z procesu kosztowego

Kwalifikacja faktury zakupowej wpływa na pola i statusy robocze, między innymi:

- `accounting_qualified`
- `accounting_notes`
- `review_status`
- `erp_status`

Pozytywna kwalifikacja ustawia dokument jako gotowy do dalszego procesu księgowego, a negatywna blokuje go w obiegu.

### 7. Proces księgowy i batchowanie

Aplikacja posiada wydzielony moduł księgowy dla dalszej obsługi faktur, głównie zakupowych.

Dostępne możliwości:

- zmiana statusu księgowego faktury
- zapis notatek księgowych
- oznaczanie kwalifikacji księgowej dokumentu
- generowanie miesięcznych batchy księgowych dla zakwalifikowanych faktur zakupowych
- listowanie batchy księgowych
- pobieranie szczegółów batcha księgowego

Obsługiwane statusy księgowe obejmują obecnie:

- `new`
- `verified`
- `posted`
- `booked`
- `cancelled`

Po ustawieniu statusu `booked` aplikacja:

- oznacza dokument jako zakończony po stronie ERP
- zapisuje odpowiedni event
- tworzy zadanie `SEND_BOOKED_NOTIFICATION`

Generowanie batcha miesięcznego powoduje:

- wybór zakwalifikowanych faktur zakupowych bez przypisanego batcha
- przypisanie ich do nowego batcha
- zmianę statusu ERP dokumentów na `ACCOUNTING_BATCHED`
- utworzenie zadania `SEND_ACCOUNTING_BATCH`

### 8. Powiadomienia

System posiada moduł powiadomień oparty o log zdarzeń i wysyłkę e-mail.

Aktualnie wspierane funkcje:

- utworzenie powiadomienia dla faktury
- ręczne wysłanie wskazanego powiadomienia
- listowanie historii powiadomień
- automatyczne tworzenie powiadomień po zaksięgowaniu faktury

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

- worker działający w pętli i stale pobierający kolejne zadania z bazy
- scheduler APScheduler wywołujący przetwarzanie zadania w stałym interwale

Obsługiwane typy zadań obejmują obecnie:

- `SEND_TO_KSEF`
- `POLL_KSEF_STATUS`
- `SEND_BOOKED_NOTIFICATION`
- `SEND_ACCOUNTING_BATCH`

Worker:

- pobiera tylko zadania o statusie `NEW`
- oznacza je jako `PROCESSING`
- zapisuje metadane blokady roboczej
- kończy zadanie statusem `DONE` albo `FAILED`

### 13. Endpointy systemowe i developerskie

Poza główną logiką biznesową aplikacja udostępnia także:

- `/health` do prostego sprawdzenia dostępności aplikacji
- `/docs` z dokumentacją Swagger generowaną przez FastAPI
- `/api/me` do pobrania danych bieżącego użytkownika i jego ról
- `/static` do serwowania zasobów statycznych interfejsu WWW

### 14. Najważniejszy przebieg end-to-end

Najważniejszy obecnie scenariusz działania aplikacji wygląda tak:

1. Użytkownik tworzy draft faktury.
2. System wylicza sumy, zapisuje strony i pozycje oraz dodaje event utworzenia.
3. Użytkownik waliduje i akceptuje fakturę.
4. System generuje XML, zapisuje payload, ustawia statusy i dodaje zadanie `SEND_TO_KSEF`.
5. Worker lub scheduler przetwarza zadanie integracyjne.
6. W trybie `mock` faktura otrzymuje numer KSeF od razu, a w trybie `live` system przechodzi przez polling statusu.
7. Po dalszej obsłudze księgowej dokument może otrzymać status `booked`, co tworzy zadanie wysyłki powiadomienia.
8. Dla faktur zakupowych możliwe jest dodatkowo kwalifikowanie do batcha księgowego i wysyłka informacji o batchu.

## Krok 7. Utwórz lub zaktualizuj schemat bazy

Ten krok przygotowuje strukturę bazy danych przed załadowaniem słowników i utworzeniem użytkownika administratora. Repozytorium zawiera teraz migracje Alembic, więc to one są preferowanym sposobem tworzenia i aktualizowania schematu.

Dla pustej bazy lub przy aktualizacji istniejącej struktury uruchom:

```bash
alembic upgrade head
```

Skrypt `python scripts/create_tables.py` pozostaje pomocniczą opcją tylko do jednorazowego bootstrapu pustej lokalnej bazy. Nie służy do aktualizacji istniejącego schematu.

## Krok 8. Załaduj dane słownikowe

Ten krok wypełnia bazę danymi referencyjnymi, z których aplikacja korzysta od razu po starcie. Skrypt dodaje brakujące słowniki i role systemowe, między innymi:

- kierunki faktur, na przykład `SALE` i `PURCHASE`
- typy faktur, na przykład `STANDARD`, `CORRECTION`, `ADVANCE`
- role stron dokumentu, na przykład `SELLER`, `BUYER`, `ISSUER`, `RECIPIENT`
- statusy obiegu KSeF, na przykład `DRAFT`, `SENT`, `ACCEPTED`, `ERROR`
- typy payloadów integracyjnych
- role użytkowników, na przykład `admin`, `agent`, `reviewer`, `accountant`, `viewer`

Skrypt nie powinien duplikować istniejących wpisów, więc można go uruchomić bezpiecznie także wtedy, gdy część danych została już wcześniej dodana.

```bash
python scripts/seed_reference_data.py
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
python scripts/create_admin.py
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

Ten proces działa w pętli i pobiera z bazy kolejne zadania integracyjne ze statusem `NEW`. Obsługuje między innymi wysyłkę do KSeF, odpytywanie o status KSeF oraz wysyłkę powiadomień.

```bash
python -m app.workers.job_worker
```

Scheduler:

Ten proces uruchamia harmonogram APScheduler, który cyklicznie wywołuje przetwarzanie kolejki zadań. To alternatywa dla ciągle działającego workera, gdy chcesz uruchamiać obsługę zadań w interwale czasowym.

```bash
python -m app.workers.scheduler
```

## Krok 13. Uruchom testy

Minimalny zestaw testów regresyjnych obejmuje walidację wyliczeń faktur, logikę retry workera oraz integralność nowych constraintów modelu.

```bash
python -m pytest tests
```

## Skrócona kolejność działań

1. `cd ksef_app`
2. Utwórz i aktywuj `.venv` na Windows albo macOS
3. `pip install -r requirements.txt`
4. Wykonaj blok SQL tworzący bazę i użytkownika MySQL
5. Skopiuj `.env.example` do `.env`
6. Uzupełnij ustawienia bazy, `SECRET_KEY` i `ADMIN_DEFAULT_PASSWORD`
7. `alembic upgrade head`
8. `python scripts/seed_reference_data.py`
9. `python scripts/create_admin.py`
10. `uvicorn main:app --reload --host 127.0.0.1 --port 8000`
