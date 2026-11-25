# Wnioski przeniesione z `master2`

## 1. Co warto zachować

Poprzedni projekt dostarczył kilka sprawdzonych wzorców:

- event-driven replay zamiast barowego przybliżenia,
- osobne typy quote, trade, order i fill,
- rozdzielenie strategii od execution modelu,
- jawny placement/cancel latency i cancel/fill race,
- cash ledger jako źródło prawdy o PnL,
- config-driven runy oraz snapshot configu przy wynikach,
- małe, deterministyczne testy mechaniki wykonania,
- raportowanie danych diagnostycznych zamiast samego końcowego PnL.

Nowy projekt powinien przejąć te zasady, ale nie kopiować całego starego silnika.
`master2` był rozwijany wokół jednego instrumentu i ma wiele historycznych
warstw strategii. Sprzężone kontrakty wymagają portfela i risk managera
zaprojektowanych od początku dla dwóch nóg.

## 2. Najważniejsza lekcja: backtest jest twierdzeniem o fillach

Każdy dodatni wynik market makingu zależy od twierdzenia, że nasze historycznie
nieistniejące zlecenie naprawdę dostałoby fill. Uproszczenia prawie zawsze
działają w jednym kierunku: przyznają za dużo korzystnych filli.

Dlatego wynik musi odpowiadać nie tylko na pytanie „jaki był PnL?”, ale również:

- gdzie znajdował się order względem best bid/ask,
- ile kolejki było przed nim,
- jaki trade zużył tę kolejkę,
- czy order nie stał się marketable podczas latency,
- czy cena leżała na prawdziwej siatce tickowej,
- czy końcową pozycję rzeczywiście można było zamknąć po raportowanej cenie.

## 3. Dziesięć reguł uczciwego księgowania

### 3.1. Prawdziwa siatka cenowa

Kwoty muszą leżeć na tick gridzie z configu. W `master2` błędny tick stworzył
fikcyjne poziomy inside-spread i pozorny edge. Bid zaokrąglamy w dół, ask w górę;
odrzucone post-only quote zapisujemy w logu.

### 3.2. Kolejka zamiast first-touch

Fill tylko dlatego, że trade dotknął naszej ceny, oznacza założenie absolutnego
front-of-queue. Przy L1 prowadzimy konserwatywne `queue_ahead` i pokazujemy
wrażliwość wyniku na `queue_fraction`.

### 3.3. Poprawna strona agresora

Sell może wypełnić bida, buy może wypełnić aska. Nieznanej strony nie wolno
cicho mapować na dowolną wartość. Trade-through jest osobnym, jednoznacznym
przypadkiem.

### 3.4. Post-only sprawdzane na aktywacji

Pasywny order może przez latency dojść do rynku już jako marketable. W nowym
MVP post-only jest wtedy odrzucany. Nie może dostać maker filla po swoim starym,
korzystnym limicie.

### 3.5. Cancel pozostaje ryzykowny do skuteczności

Cancel request nie usuwa orderu natychmiast. Order może dostać fill w oknie
cancel latency. Każde wywołanie cancel musi nieść aktualny timestamp.

### 3.6. Cena wyjścia musi być wykonywalna

Mark po midzie jest diagnostyką, a nie bankowalnym PnL. Long zamyka się po
bidzie, short po asku, z fee i slippage. Dotyczy to pojedynczego filla, całej
pozycji i wymuszonego wyjścia o 11:45.

### 3.7. Pozycja jest częścią strategii

Per-fill markout nie zastępuje symulacji portfela. Jednostronne fille mogą
doprowadzić pozycję do limitu i pozostawić cały „zysk” w niezrealizowanym marku.
Trzeba raportować realized, mid-mark, liquidation oraz matched-volume PnL.

### 3.8. Opłaty i rebates są jawne

Maker fee/rebate oraz taker fee końcowego wyjścia są osobnymi pozycjami raportu.
Nie należy zakładać tieru, którego wolumen strategii nie jest w stanie osiągnąć.

### 3.9. Jeden zegar i brak lookahead

Osobne pliki quote/trade nie dają automatycznie wspólnej kolejności. Używamy
offset-aware timestampów, batchujemy remisy i przyjmujemy trade-before-quote.
Każdy lookup jest backward/as-of. Future quote ani finalny realized spread nie
mogą przeciekać do decyzji.

### 3.10. Replikacja i kontrole

Parametry wybieramy na innych dniach niż ocena. Dodatni wynik powinien pokonać
co najmniej niezależny MM bez sprzężenia oraz placebo/odwrócony target przy tej
samej liczbie okazji i identycznym execution modelu.

## 4. Lekcje specyficzne dla dwóch kontraktów

### Target to prognoza, nie warunek danych

`B-A=-5` o 11:45 jest przekonaniem strategii. Backtester nie może wymusić tej
wartości ani użyć jej do terminalnego marku. Raportuje rzeczywisty spread o
wyjściu i forecast error.

### Trafna prognoza nie gwarantuje zysku market makera

Nawet jeśli basis finalnie zmierza do `-5`, fille mogą być selektywnie
niekorzystne. Rynek może wypełniać tylko nogę, która zaraz dalej traci. Dlatego
oddzielamy:

- spread capture,
- PnL ze zmiany basis,
- koszt leggingu,
- koszt końcowej likwidacji,
- fees.

### Ryzyko jednej nogi i ryzyko pary są różne

Pozycje `A` i `B` przeliczamy do wspólnej jednostki. Kontrolujemy zarówno
`common = x_A+x_B`, jak i `spread = x_B-x_A`. Sam limit na każdej nodze nie
chroni przed dużym gross ani przed parą ustawioną w złą stronę.

### Fille obu nóg są asynchroniczne

Nie wolno księgować „pair fill”, jeśli historycznie wykonała się tylko jedna
noga. Backtester mierzy czas niezhędżowanej ekspozycji i wszystkie próby
domknięcia drugiej nogi. Natychmiastowy hedge takerem jest oddzielną, płatną
polityką, a nie darmowym założeniem.

### Stary rynek jednej nogi zatruwa fair value obu

Coupled fair value wymaga dwóch świeżych książek. Jeśli jedna jest stale, nowe
kwoty na obu nogach są wstrzymane. Nie interpolujemy brakującej ceny i nie
zastępujemy jej targetem.

## 5. Czego nie przenosić ze starego repo

### Jednego scalar inventory

Stary `OrderManager` był zoptymalizowany pod jeden instrument. Nowy portfolio
ledger musi być mapą `contract_id -> position/cash flows` i liczyć ekspozycje
portfelowe.

### Mark-to-mid jako wynik końcowy

To może pozostać pomocniczą krzywą equity, ale nie headline PnL. Gap lub koniec
dnia nie może magicznie zamykać pozycji po midzie.

### Price-only fill i natychmiastowy fill na touchu

To front-of-queue oracle. W MVP bazą jest kolejka L1; tryb optymistyczny może
istnieć wyłącznie jako jawna granica sensitivity analysis.

### Automatycznego zgadywania schematu

Stary loader akceptował wiele nazw kolumn, heurystycznie zgadywał jednostki czasu
i mapował nieznane strony. Prywatny CSV ma jeden wersjonowany schemat, jawny
offset czasu i fail-fast validation.

### Monolitycznego runnera i niejawnych defaultów

Config ma być walidowany, kompletny i kopiowany do wyników. Nieznane klucze są
błędem. Strategia, execution i raport nie powinny być jednym wielkim skryptem.

### Złożoności A-S/GLFT na start

Pierwsze pytanie jest prostsze: czy jawna relacja `B-A -> -5`, po realnym
execution i wyjściu, poprawia wynik względem niezależnego MM? Klasyczne modele
optymalnych spreadów nie są potrzebne do odpowiedzi i utrudniłyby audyt.

### Dopasowania relacji na całej próbce

Historyczny eksperyment pairs/cointegration obliczał część parametrów na pełnym
zbiorze przed podziałem IS/OOS. Nowy model nie może estymować hedge ratio,
średniej spreadu ani ścieżki zbieżności z przyszłości dnia testowego. Fit odbywa
się na train lub rozwijającym oknie wyłącznie z przeszłości.

## 6. Kontrole eksperymentalne

Każdy właściwy run powinien mieć porównywalne warianty na tym samym tape:

1. **Independent MM** — te same szerokości, limity i execution, bez targetu.
2. **Coupled MM** — fair value i inventory sprzężone przez target `-5`.
3. **Placebo** — odwrócony target albo target przypisany z innego dnia, bez
   zmiany częstotliwości decyzji.
4. **Fill sensitivity** — konserwatywna, bazowa i optymistyczna kolejka L1.
5. **Fee sensitivity** — realne osiągalne tiery maker/taker.

Wynik coupled ma sens tylko wtedy, gdy przewaga nie pochodzi wyłącznie z bardziej
agresywnego inventory, większego gross albo uprzywilejowanego modelu filli.

## 7. Metryki, które zapobiegają fałszywym wnioskom

Poza net PnL zapisujemy:

- wynik po pełnej likwidacji i wynik matched-volume-only,
- terminalny mid mark tylko jako porównanie,
- maker/taker notional i opłaty,
- fills, queue consumption i post-only rejections,
- peak/average A, B, common, spread i gross inventory,
- czas z jedną niezhędżowaną nogą,
- koszt forced exit,
- rzeczywisty basis o 11:45 oraz błąd prognozy,
- PnL w rozbiciu na spread capture, basis move i liquidation,
- liczbę stale-book, gap oraz incomplete-exit,
- wynik per dzień, nie tylko sumę z całego okresu.

## 8. Reprodukowalność i prywatność

Nowe repo nie potrzebuje zewnętrznych bibliotek. Standardowa biblioteka
wystarcza do czytania CSV, precyzyjnej arytmetyki, CLI, JSON i testów:

- `csv`, `decimal`, `datetime`, `zoneinfo`,
- `dataclasses`, `enum`, `heapq`,
- `argparse`, `json`, `hashlib`,
- `unittest`.

Każdy run zapisuje pełny config, SHA-256 inputów, wersję schematu i execution
modelu. Prywatne CSV pozostają poza Gitem. Testy używają krótkich, ręcznie
policzalnych fixture'ów syntetycznych obejmujących także ujemne ceny, partial
fille, batch ties, cancel race i brak rynku na wyjściu.

## 9. Kryterium gotowości MVP

MVP jest gotowy do przyjęcia prywatnych danych dopiero, gdy:

- przechodzi walidację obu CSV i offsetów czasu,
- wynik nie zależy od kolejności A/B wewnątrz batcha,
- żaden order nie wypełnia się zdarzeniem, które go utworzyło,
- kolejka zachowuje wolumen i partial fills,
- ceny quote są na tick gridzie i post-only,
- limity obejmują live oraz pending orders obu nóg,
- po cutoffie nie powstają nowe passive orders,
- finalny long wychodzi po bidzie, short po asku,
- brak wykonywalnej ceny daje `incomplete_exit`, nie mark po midzie,
- cash po pełnym zamknięciu zgadza się z ręcznie policzonym PnL,
- drugi replay jest deterministycznie identyczny.

