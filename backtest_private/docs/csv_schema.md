# Schemat prywatnych danych CSV

## 1. Zasady ogólne

Dane rynkowe są dostarczane w dwóch osobnych plikach:

- plik L1 quotes,
- plik trades.

Format obu plików:

- kodowanie UTF-8,
- separator `,`,
- jeden wiersz nagłówka,
- kropka jako separator dziesiętny,
- brak separatorów tysięcy,
- brak `NaN`, `Infinity` i pustych pól obowiązkowych,
- czas ISO 8601 z jawnym offsetem UTC.

Przykładowa konwencja nazw:

```text
quotes_2026-01-15.csv
trades_2026-01-15.csv
```

Pliki mogą mieć inne nazwy przekazane w CLI, ale ich schemat pozostaje taki sam.
Surowe CSV są prywatne i nie powinny trafiać do Gita. W repo może znajdować się
wyłącznie mały, syntetyczny fixture.

## 2. Czas

Pole `timestamp` jest obowiązkowym, offset-aware czasem ISO 8601, np.:

```text
2026-01-15T11:42:03.125000+01:00
2026-06-15T11:42:03.125000+02:00
2026-06-15T09:42:03.125000Z
```

Niedozwolony jest czas naiwny:

```text
2026-01-15 11:42:03
```

Loader zachowuje oryginalny timestamp do audytu, a do sortowania normalizuje go
do UTC. Offset w każdym wierszu rozwiązuje niejednoznaczności CET/CEST i DST.
Godzina wyjścia 11:45 jest interpretowana w strefie sesji z configu; musi
odpowiadać poprawnemu offsetowi zapisanym w danych.

W ramach każdego pliku rekordy muszą być uporządkowane niemalejąco po
`timestamp`. Naruszenie kolejności jest błędem danych, a nie sygnałem do cichego
sortowania. Rekordy o identycznym timestampie są dozwolone i tworzą batch.

## 3. Identyfikatory kontraktów

Każdy rekord ma `contract_id`. Config mapuje identyfikatory dostawcy na role:

```text
A = kontrakt na 12:00
B = kontrakt na 12:30
```

Przykład:

```json
{
  "contract_a": "ENERGY_20260115_1200",
  "contract_b": "ENERGY_20260115_1230"
}
```

Identyfikator jest nieprzezroczystym stringiem. Backtester nie wyciąga czasu
dostawy z jego nazwy. W jednym runie dozwolone są dokładnie kontrakty wskazane w
configu; obcy `contract_id` powoduje błąd.

## 4. Plik quotes

### Obowiązkowe kolumny

```text
timestamp,contract_id,bid_price,bid_size,ask_price,ask_size
```

| Kolumna | Typ logiczny | Znaczenie |
|---|---|---|
| `timestamp` | offset-aware datetime | Czas stanu L1 na giełdzie |
| `contract_id` | string | Id kontraktu A albo B |
| `bid_price` | Decimal | Najlepsza cena kupna; może być ujemna |
| `bid_size` | Decimal | Widoczny rozmiar na najlepszym bidzie |
| `ask_price` | Decimal | Najlepsza cena sprzedaży; może być ujemna |
| `ask_size` | Decimal | Widoczny rozmiar na najlepszym asku |

Każdy rekord jest pełnym snapshotem L1, nie deltem. Musi spełniać:

```text
bid_price < ask_price
bid_size >= 0
ask_size >= 0
```

Cena może być równa zero lub ujemna. Bid i ask muszą leżeć na siatce tickowej
kontraktu zapisanej w configu.

### Kolumny opcjonalne

```text
sequence,source_row_id
```

- `sequence` — całkowity numer sekwencyjny dostawcy w obrębie strumienia,
- `source_row_id` — stabilny identyfikator rekordu do audytu.

Jeżeli `sequence` występuje, musi rosnąć dla danego kontraktu i nie może mieć
duplikatów. Bez niego deterministycznym tie-breakerem jest numer wiersza w pliku.

### Przykład

```csv
timestamp,contract_id,bid_price,bid_size,ask_price,ask_size,sequence
2026-01-15T11:42:03.125000+01:00,ENERGY_20260115_1200,101.5,8,102.0,10,8401
2026-01-15T11:42:03.125000+01:00,ENERGY_20260115_1230,99.0,6,99.5,9,9104
2026-01-15T11:42:03.400000+01:00,ENERGY_20260115_1200,101.0,12,101.5,7,8402
```

## 5. Plik trades

### Obowiązkowe kolumny

```text
timestamp,contract_id,price,size,aggressor_side
```

| Kolumna | Typ logiczny | Znaczenie |
|---|---|---|
| `timestamp` | offset-aware datetime | Czas transakcji na giełdzie |
| `contract_id` | string | Id kontraktu A albo B |
| `price` | Decimal | Cena transakcji; może być ujemna |
| `size` | Decimal | Dodatni rozmiar transakcji |
| `aggressor_side` | enum | Wyłącznie `BUY` albo `SELL` |

`BUY` oznacza agresora kupującego, który uderzył w ask. `SELL` oznacza agresora
sprzedającego, który uderzył w bid. Nieznana albo pusta strona nie jest
automatycznie mapowana na `SELL`; loader ma przerwać run z czytelnym błędem.

Wymagania:

```text
size > 0
aggressor_side in {BUY, SELL}
```

### Kolumny opcjonalne

```text
trade_id,sequence,source_row_id
```

- `trade_id` — id transakcji dostawcy; duplikaty są błędem,
- `sequence` — numer sekwencyjny, jeśli dostawca go udostępnia,
- `source_row_id` — id wiersza do audytu.

### Przykład

```csv
timestamp,contract_id,price,size,aggressor_side,trade_id
2026-01-15T11:42:03.125000+01:00,ENERGY_20260115_1200,101.5,3,SELL,T-55001
2026-01-15T11:42:03.125000+01:00,ENERGY_20260115_1230,99.5,2,BUY,T-55002
2026-01-15T11:42:04.010000+01:00,ENERGY_20260115_1200,101.0,5,SELL,T-55003
```

## 6. Reguły łączenia quote i trade

Loader zachowuje źródłowy numer wiersza. Silnik scala rekordy po timestampie w
UTC i tworzy batch dla każdej unikalnej chwili.

W batchu:

1. wszystkie trades są rozliczane na książce i orderach istniejących przed tym
   timestampem,
2. następnie stosowane są quotes,
3. strategia jest wywoływana raz po całym batchu.

Quote o 11:42:03.125 nie może zostać użyty do nadania fillu trade'owi o tym
samym timestampie. Jest to świadoma, konserwatywna zasada zapobiegająca
lookaheadowi, gdy dwa osobne pliki nie zawierają wspólnej, wiarygodnej sekwencji.

## 7. Jednostki i metadane w configu

CSV nie koduje domyślnych jednostek. Config musi jawnie określić dla każdego
kontraktu:

- `tick_size`,
- `lot_size`,
- `multiplier` — np. MWh przypadające na jednostkę pozycji,
- walutę,
- strefę sesji,
- rolę A/B i czas dostawy.

Oba pliki muszą używać tych samych jednostek ceny i rozmiaru. Loader nie zgaduje
czy `size` oznacza loty, MWh lub notional.

## 8. Walidacja przed backtestem

Run nie powinien się rozpocząć, dopóki nie przejdą przynajmniej następujące
kontrole:

1. Oba nagłówki zawierają wszystkie obowiązkowe kolumny.
2. Każdy timestamp ma offset i daje się znormalizować do UTC.
3. Czas w każdym pliku jest niemalejący.
4. Występują tylko dwa oczekiwane `contract_id`.
5. Każda noga ma quote przed rozpoczęciem kwotowania.
6. Quote nie jest crossed i ma nieujemne rozmiary.
7. Quote i trade leżą na poprawnej siatce tickowej, jeśli venue gwarantuje taki
   warunek dla trade.
8. Trade ma dodatni size i stronę `BUY` albo `SELL`.
9. `trade_id`, `sequence` i `source_row_id`, jeśli występują, nie mają
   niedozwolonych duplikatów.
10. W danych istnieje świeży quote obu nóg w pobliżu planowanego wyjścia.

Ostatnia kontrola nie gwarantuje jeszcze wyjścia: jeśli runtime nie znajdzie
świeżego, wykonywalnego booka po uwzględnieniu latency, wynik ma status
`incomplete_exit`.

## 9. Brakujące lub niepełne dane

- Brak quote jednej nogi blokuje coupled fair value i nowe kwoty.
- Quote starszy niż `max_quote_age` powoduje cancel obu nóg.
- Luka czasowa większa niż limit jest zapisywana w raporcie; nie jest wypełniana
  interpolowanym midem.
- Plik trade zawierający tylko nagłówek może być użyty wyłącznie w jawnym trybie
  diagnostycznym. W konserwatywnym modelu nie daje pasywnych filli.
- Nie wolno forward-fillować poza skonfigurowany limit świeżości.
- Nie wolno tworzyć syntetycznej ceny końcowej z targetu `B-A=-5`.

## 10. Prywatność i reprodukowalność

Surowe pliki wejściowe powinny być ignorowane przez Git. Raport runu zapisuje
co najmniej:

- ścieżkę lub logiczną nazwę obu plików,
- SHA-256 każdego pliku,
- liczbę zaakceptowanych i odrzuconych rekordów,
- zakres timestampów,
- kompletny snapshot configu,
- wersję schematu, np. `energy_csv_v1`.

Dzięki temu prywatnych danych nie trzeba publikować, aby jednoznacznie wskazać,
na jakim zbiorze powstał wynik.

