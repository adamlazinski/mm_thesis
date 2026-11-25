# Projekt backtestera dla sprzężonych kontraktów energii

## 1. Cel i granice pierwszej wersji

Backtester ma oceniać market making na dwóch powiązanych kontraktach:

- `A` — kontrakt na 12:00,
- `B` — kontrakt na 12:30,
- teza strategii — o 11:45 spread `B - A` wyniesie `-5` punktów.

Do 11:45 strategia może wystawiać pasywne zlecenia po obu stronach obu
kontraktów. Teza o spreadzie wpływa na fair value i kwoty, ale **nie jest ceną
rozliczenia**. O 11:45 każda pozostała pozycja jest zamykana po rzeczywistym,
wykonywalnym bidzie albo asku z danych. Jeśli rynek nie zbiegnie do `-5`, wynik
ma pokazać zysk lub stratę tej pomyłki.

Pierwsza wersja ma być mała, deterministyczna i oparta wyłącznie na bibliotece
standardowej Pythona. Nie modeluje wpływu naszych zleceń na rynek ani pełnej
książki L2/L3. Wynik jest więc scenariuszem zależnym od jawnie wybranego modelu
kolejki L1, a nie rekonstrukcją prawdziwej pozycji w kolejce.

## 2. Zasady konstrukcyjne

1. Wszystkie decyzje są przyczynowe: strategia widzi wyłącznie zdarzenia już
   przetworzone.
2. Quote i trade o tym samym czasie tworzą jeden batch; trade jest obsługiwany
   przed quote.
3. Zlecenie utworzone po batchu nie może dostać fillu ze zdarzenia, które je
   utworzyło.
4. Stan portfela i ryzyko obejmują obie nogi łącznie.
5. Ceny zleceń leżą na rzeczywistej siatce tickowej i respektują post-only.
6. Fille maker wynikają z transakcji oraz jawnego modelu kolejki, nigdy z samego
   dotknięcia ceny.
7. Końcowy PnL opiera się na wykonywalnym wyjściu, nie na marku po midzie.
8. Ten sam input i config zawsze dają identyczny wynik.

## 3. Podział odpowiedzialności

Kod powinien pozostać rozdzielony na kilka prostych warstw.

### Loader i walidator

Loader czyta osobne pliki quote i trade przez `csv.DictReader`, parsuje liczby
przez `decimal.Decimal`, a czasy przez `datetime.fromisoformat`. Zwraca typowane
dataclassy. Walidator odrzuca błędne timestampy, nieznane kontrakty, crossed
book, wartości spoza siatki tickowej i niepoprawne strony transakcji.

### Strumień zdarzeń

Strumień scala oba pliki bez utraty identyfikatora kontraktu. Zdarzenia są
porządkowane według:

```text
(timestamp_utc, priorytet_typu, kolejność_źródłowa)
```

Priorytet typu to trade przed quote. Rekordy z tym samym timestampem są jednak
przetwarzane jako jeden atomowy batch, a strategia jest uruchamiana dopiero po
całym batchu. Dzięki temu przypadkowa kolejność rekordów A i B w pliku nie
zmienia decyzji.

### Stan rynku

Dla każdego `contract_id` przechowywany jest osobny `BookState`:

- ostatni bid, ask i ich rozmiary,
- timestamp ostatniego quote,
- ostatni trade,
- tick size oraz mnożnik kontraktu.

Jeżeli quote którejkolwiek nogi jest starszy niż `max_quote_age`, strategia nie
może dodawać ryzyka i anuluje pasywne zlecenia na obu nogach.

### Strategia

Strategia dostaje niezmienny widok obu książek, portfela i czasu. Zwraca wyłącznie
intencje zleceń. Nie księguje filli i nie modyfikuje silnika wykonania.

### Risk manager

Risk manager sprawdza intencje razem z aktualną pozycją oraz wszystkimi live i
pending orders. Kontroluje limity każdej nogi, ekspozycję wspólną, ekspozycję na
spread oraz gross. Odrzucona intencja jest zapisywana z powodem.

### Execution model

Execution model zarządza cyklem życia zleceń, latency, kolejką L1, partial
fillami, post-only i opłatami. Jest jedynym komponentem uprawnionym do tworzenia
`Fill`.

### Portfolio i raport

Portfolio prowadzi pozycję per kontrakt, cash ledger i opłaty. Raport oddziela
maker PnL, koszt końcowego wyjścia, opłaty, ekspozycję oraz błędy/stany
niekompletne.

## 4. Reprezentacja cen i ilości

Ceny i ilości wczytujemy jako `Decimal`. Cena energii może być ujemna, dlatego
walidacja nie może zakładać `price > 0`. Tick musi być dodatni.

Ceny zleceń najlepiej przeliczać na całkowitą liczbę ticków. Bid zaokrąglamy w
dół, ask w górę. Zapobiega to phantom quotes pomiędzy poziomami dopuszczonymi
przez rynek.

Pozycje różnych kontraktów porównujemy po przeliczeniu na wspólną jednostkę,
np. MWh:

```text
x_A = position_A * multiplier_A
x_B = position_B * multiplier_B
```

## 5. Semantyka czasu i brak lookahead

Dla timestampu `t` silnik wykonuje następujące kroki:

1. Aktywuje submit/cancel skuteczne **ściśle przed** `t`.
2. Zapamiętuje zbiór zleceń, które były aktywne przed zdarzeniami `t`.
3. Przetwarza wszystkie trades z `t` na tym zbiorze zleceń.
4. Aktualizuje quotes z `t`.
5. Rozstrzyga operacje z `effective_ts == t`: nowy order nie uczestniczył w
   trades z `t`, a cancel mógł jeszcze przegrać race i dostać fill.
6. Aktualizuje portfolio i wskaźniki ryzyka.
7. Uruchamia strategię dokładnie raz po całym batchu.
8. Waliduje intencje i planuje ich wejście w życie po latency.

Żaden as-of lookup nie może wybierać rekordu późniejszego niż czas decyzji.
Przy wyszukiwaniu w szeregu używamy ostatniego elementu `<= t`. Terminalna teza
`-5` jest parametrem znanym przed sesją, a nie informacją odczytaną z końca dnia.

## 6. Coupled fair value

Niech:

- `m_A`, `m_B` — aktualne midy,
- `s_obs = m_B - m_A` — obserwowany spread,
- `s_target = -5`,
- `lambda(t)` — deterministyczna waga zbieżności z przedziału `[0, 1]`, rosnąca
  w kierunku 11:45,
- `c_A`, `c_B` — dodatnie zaufanie do obu midów.

Definiujemy:

```text
delta = lambda(t) * (s_target - s_obs)

fair_A = m_A - c_B / (c_A + c_B) * delta
fair_B = m_B + c_A / (c_A + c_B) * delta
```

Wtedy:

```text
fair_B - fair_A = (1 - lambda) * s_obs + lambda * s_target
```

Przy równych wagach, `m_A = m_B = 100` i `lambda = 1` otrzymujemy
`fair_A = 102.5`, `fair_B = 97.5`. Korekta rozkłada się symetrycznie na obie
nogi.

Przykładowa ścieżka zbieżności:

```text
progress = clip((now - strategy_start) / (exit_time - strategy_start), 0, 1)
lambda = progress ** convergence_gamma
```

Ścieżka jest elementem hipotezy i configu. Nie wolno dopasowywać jej do
przyszłych cen dnia, który właśnie backtestujemy.

## 7. Sprzężony inventory skew

Dwie podstawowe ekspozycje to:

```text
common = x_A + x_B
spread = x_B - x_A
```

`common` opisuje kierunkowe ryzyko poziomu cen, a `spread` — ryzyko relacji B-A.
Koszt ryzyka może mieć postać:

```text
C = 0.5 * k_common * common^2 + 0.5 * k_spread * spread^2
```

Reservation price każdej nogi jest fair value pomniejszonym o marginalny koszt
dodatkowej pozycji. W rezultacie fill na A musi zmienić kwoty nie tylko na A,
ale też na B. Parametry ryzyka mogą rosnąć przed końcem sesji, aby ograniczać
pozycję przed wymuszonym wyjściem.

Limity minimalne:

- maksymalna bezwzględna pozycja A i B,
- maksymalne `abs(common)`,
- maksymalne `abs(spread)`,
- maksymalny gross,
- maksymalny rozmiar pojedynczego zlecenia.

Sprawdzenie uwzględnia jednocześnie pending i live orders, aby dwa fille w tym
samym batchu nie przekroczyły limitu tylko z powodu kolejności księgowania.

## 8. Budowanie kwot

Dla każdej nogi:

```text
raw_bid = reservation - half_width
raw_ask = reservation + half_width

bid = floor_to_tick(raw_bid)
ask = ceil_to_tick(raw_ask)
```

Następnie stosujemy post-only:

- bid nie może przecinać aktualnego aska,
- ask nie może przecinać aktualnego bida,
- crossed lub pusty book wyłącza kwotowanie,
- cena zbyt daleka od rynku jest odrzucana,
- po jednej aktywnej kwocie na stronę i kontrakt.

Cancel/replace następuje dopiero po zmianie co najmniej `refresh_ticks`, zmianie
rozmiaru, naruszeniu ryzyka albo przekroczeniu maksymalnego wieku orderu. Samo
przeliczenie fair value nie powinno automatycznie zerować pozycji w kolejce.

## 9. Model wykonania L1

### Aktywacja i post-only

Order zaczyna być aktywny po `new_order_latency`. Na aktywacji jest sprawdzany
względem ostatniej książki niepóźniejszej niż `effective_ts`. Jeśli pasywny order
stał się marketable, zostaje odrzucony jako post-only; nie dostaje wygodnego
maker filla po starej cenie.

Końcowe zlecenia zamykające są oddzielnym typem IOC/taker i nie podlegają
post-only.

### Kolejka na touchu

Przy dołączeniu do aktualnego best price:

```text
queue_ahead = displayed_size * queue_fraction
```

Przy poprawieniu best price `queue_ahead = 0`. Dla orderu schowanego za touchem
L1 nie zna kolejki; taki order może dostać fill dopiero po jednoznacznym
trade-through.

Dla aktywnego bida po `p`:

- tylko agresywny sell może go wypełnić,
- sell dokładnie po `p` najpierw zmniejsza `queue_ahead`, a dopiero potem nasz
  remaining quantity,
- sell poniżej `p` oznacza trade-through i wypełnia pozostałą ilość.

Dla aska reguły są symetryczne. Wolumen pojedynczego trade nie może zostać użyty
ponownie przez kilka naszych orderów na tym samym poziomie. Spadek widocznego
size bez trade nie zmniejsza kolejki w konserwatywnym MVP.

### Cancel race

Po żądaniu anulowania order pozostaje aktywny do `cancel_effective_ts`. Może w
tym czasie dostać fill. Replace nie może tworzyć niezamierzonego nakładania się
starej i nowej ekspozycji.

## 10. Wyjście o 11:45

Pasywne kwotowanie kończy się wcześniej:

```text
quote_cutoff = exit_time - cancel_latency - cancel_safety_buffer
```

Od cutoffu silnik:

1. nie przyjmuje nowych pasywnych zleceń,
2. wysyła cancel dla wszystkich live orders,
3. nadal rozlicza prawidłowe fille z cancel race,
4. o 11:45 zamyka pozostałe pozycje po wykonywalnym rynku.

Long jest sprzedawany po bidzie, short odkupowany po asku, z taker fee i
konfigurowanym slippage. Przy latency wyjścia używamy pierwszego quote dostępnego
po czasie skuteczności zlecenia, nigdy wcześniejszego.

Jeśli brakuje świeżego rynku którejkolwiek nogi w `max_exit_delay`, run otrzymuje
status `incomplete_exit`. Nie wolno zastępować brakującej ceny midem ani targetem
`-5`.

## 11. Księgowanie PnL

Dla buy `sign = +1`, dla sell `sign = -1`:

```text
position_i += sign * quantity
cash -= sign * price * quantity * multiplier_i
cash -= fee
```

W trakcie sesji można raportować dwa markery:

- `equity_mid` — diagnostyczny mark po midzie,
- `equity_liquidation` — long po bidzie, short po asku, pomniejszone o koszt
  wyjścia.

Po pełnym zamknięciu wszystkich nóg cash jest autorytatywnym net PnL. Raport
powinien dodatkowo pokazać wynik na matched volume, koszt wymuszonego wyjścia i
różnicę między mid markiem a likwidacją.

## 12. Minimalny raport

- gross i net PnL,
- maker fees/rebates, taker fees i koszt końcowej likwidacji,
- PnL przypisany spread capture oraz zmianie basis,
- turnover, liczba i rozmiar filli per kontrakt,
- quote uptime i fill ratio,
- peak/average inventory A, B, common, spread i gross,
- czas spędzony z niezhędżowaną nogą,
- maksymalny drawdown liquidation equity,
- rzeczywisty `B - A` o wyjściu i błąd względem `-5`,
- status wyjścia i końcowe pozycje,
- hash configu i plików wejściowych,
- nazwa i wersja modelu filli.

## 13. Najważniejsze testy akceptacyjne

1. Order wygenerowany przez batch `t` nie dostaje fillu z batcha `t`.
2. Trade jest obsługiwany przed quote o identycznym timestampie.
3. Zamiana kolejności rekordów A/B w tym samym batchu nie zmienia wyniku.
4. `lambda=0` daje bieżące midy, a `lambda=1` daje `fair_B-fair_A=-5`.
5. Ujemne ceny i kierunkowe zaokrąglanie do ticka działają poprawnie.
6. Kolejka 10, trade 6 daje brak fillu; kolejny trade 5 daje fill 1.
7. Trade-through daje pełny fill remaining quantity.
8. Post-only crossing jest odrzucany.
9. Cancel może dostać fill w oknie latency.
10. Stara jedna noga powoduje anulowanie kwot na obu nogach.
11. Risk manager uwzględnia dowolny jednoczesny fill live/pending orders.
12. Po cutoffie nie powstają pasywne zlecenia.
13. Finalny long wychodzi po bidzie, short po asku; nigdy po midzie.
14. Brak świeżego rynku przy wyjściu daje `incomplete_exit`.
15. Dwa replaye tych samych danych i configu są bitowo zgodne w raportach.

