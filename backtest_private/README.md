# Backtester market makingu sprzężonych kontraktów energii

## Cel

To mały, deterministyczny backtester dwóch kontraktów energii:

- `POWER_1200` — noga A, kontrakt na 12:00,
- `POWER_1230` — noga B, kontrakt na 12:30.

Hipoteza strategii brzmi: o 11:45 spread `B - A` będzie równy `-5` punktów.
Do czasu wyjścia strategia market makuje na obu kontraktach, łącząc ich bieżące
midy ze stopniowo rosnącą wagą terminalnego targetu. Target jest prognozą znaną
przed sesją — backtester nie wymusza spreadu `-5` w danych i nie używa go jako
sztucznej ceny wyjścia.

Projekt jest celowo oparty wyłącznie na bibliotece standardowej Pythona. Runtime
nie wymaga instalowania pandas, numpy ani frameworka backtestowego.

## Szybki start

Wymagany jest Python 3.11 lub nowszy. Z katalogu repozytorium uruchom:

```bash
PYTHONPATH=src python3 -m coupled_mm.cli \
  --config configs/example.json \
  --quotes examples/data/quotes.csv \
  --trades examples/data/trades.csv \
  --output-dir outputs/example
```

Fixture jest syntetyczny i łatwy do ręcznego sprawdzenia:

- o 11:00 oba kontrakty mają mid równy `100`,
- model wystawia poprawiony bid A i ask B po `100`,
- późniejszy agresywny `SELL` na A oraz `BUY` na B mogą wypełnić te zlecenia,
- o 11:45 mid A wynosi `103.5`, mid B `98.5`, więc rzeczywisty spread to `-5`.

Pełny format wejścia opisuje [docs/csv_schema.md](docs/csv_schema.md), a założenia
silnika i sprzężonego fair value — [docs/design.md](docs/design.md).

Obok konfiguracji coupled są dwa obowiązkowe kontrolne warianty na ten sam
tape: `configs/independent.json` wyłącza wagę targetu, a
`configs/placebo.json` odwraca target na `+5`. Przewaga strategii ma znaczenie
dopiero wtedy, gdy coupled pokonuje oba przy identycznym execution i limitach.

## Co konfiguruje przykład

`configs/example.json` ustawia tick `0.5`, sesję 11:00–11:45 w strefie
`Europe/Warsaw`, target `B-A=-5`, kwotowanie obu nóg, limity portfela oraz model
wykonania `trade_queue`. Kwotowanie pasywne kończy się 500 ms przed wyjściem,
a cancel latency wynosi 250 ms, więc anulowania mają czas stać się skuteczne
przed 11:45.

Opłaty w fixture są zerowe wyłącznie po to, aby wynik dało się policzyć ręcznie.
Przed użyciem danych realnych trzeba wpisać faktyczne fee/rebate, latency,
mnożniki, limity oraz realistyczny parametr kolejki.

## Uczciwe ograniczenia modelu filli

Bazowy `trade_queue` nie daje filla od samego dotknięcia ceny. Bid może zostać
wypełniony tylko przez agresywny sell, ask tylko przez agresywny buy, a widoczny
wolumen przed zleceniem jest konsumowany zgodnie z `queue_fraction`.

To nadal przybliżenie oparte na L1:

- nie znamy rzeczywistej pozycji zlecenia w kolejce L2/L3,
- nie modelujemy hidden liquidity, icebergów ani reakcji rynku na nasze zlecenia,
- `queue_fraction` jest scenariuszem, nie obserwacją historyczną,
- osobne pliki quotes i trades nie odtwarzają pełnej kolejności giełdowej,
- fill obu nóg nie jest atomowy; jednostronna pozycja pozostaje realnym ryzykiem,
- końcowa pozycja jest zamykana po wykonywalnym bid/ask, a nie po midzie lub
  terminalnym targecie.

Wymuszone wyjście nie może przekroczyć widocznego rozmiaru L1. Jeśli pozycja
jest większa, run dostaje status `incomplete_exit` zamiast dopisywać fikcyjny
fill. `exit_slippage_ticks` pozwala dodatkowo pogorszyć cenę dla mieszczącego
się w L1 wyjścia; po dostarczeniu depthu L2 ten prosty model należy zastąpić
rzeczywistym sweepem kolejnych poziomów.

Wynik należy więc czytać jako rezultat pod jawnymi założeniami execution, nie
jako dowód, że historycznie nieobecne zlecenia na pewno dostałyby takie fille.
Sensowny eksperyment powinien obejmować kilka wartości `queue_fraction`, opłat
i latency oraz porównanie z market makingiem bez sprzężenia.

## Prywatne dane

Prawdziwe CSV umieszczaj w katalogu `data/`, który jest ignorowany przez Git.
Nie dodawaj ich przez `git add -f` i nie zapisuj danych wejściowych w raportach.
Śledzone pliki `examples/data/*.csv` są wyłącznie małym, sztucznym fixture'em.
Wyniki w `outputs/` również są ignorowane.

## Status MVP

To audytowalny MVP do sprawdzenia mechaniki, a nie gotowy system tradingowy.
Zakres obejmuje walidowany JSON/CSV, przyczynowy replay zdarzeń, sprzężone fair
value, pozycje i limity obu nóg, latency, kolejkę L1 oraz wymuszone wyjście o
11:45. Kolejne kroki po wgraniu prywatnych danych to adapter ich dokładnego
schematu, kalibracja wykonania, testy wielu dni oraz baseline i sensitivity
analysis bez lookaheadu. W szczególności końcowy IOC ma w MVP zerową taker
latency; przed oceną realnego wyniku trzeba dodać latency i sweep L2 właściwe dla
konkretnego venue.
