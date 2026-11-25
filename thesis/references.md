# References

Forty-two entries, **every one cited at a specific point in the chapters** — checked
mechanically by `scripts/check_citations.py`, which `scripts/build_thesis.sh` runs, in both
directions: no entry here goes uncited, and no citation in the text is missing from here. Page
numbers were checked against the
originals on 2026-11-19 for every entry carrying volume-and-page detail; the arXiv preprints are
cited by identifier because that is where they were read.

## Optimal market making

- Avellaneda, M. & Stoikov, S. (2008). High-frequency trading in a limit order book.
  *Quantitative Finance*, 8(3), 217–224.
- Barzykin, A., Bergault, P., Guéant, O. & Lemmel, F. (2025). Optimal quoting under adverse
  selection and price reading. arXiv:2508.20225.
- Barucci, E., Mathieu, A. & Sánchez-Betancourt, L. (2025). Market making with fads, informed,
  and uninformed traders. arXiv:2501.03658.
- Bergault, P., Evangelista, D., Guéant, O. & Vieira, D. (2021). Closed-form approximations in
  multi-asset market making. *Applied Mathematical Finance*, 28(2), 101–142.
  (arXiv:1810.04383. The multi-asset extension whose cross-asset skew Chapter 2 §3 measures at
  0.04 ticks and finds quantizes away.)
- Cartea, Á., Jaimungal, S. & Penalva, J. (2015). *Algorithmic and High-Frequency Trading*.
  Cambridge University Press. (Exposition of the A-S HJB solution used in Chapter 2 §2.)
- Guéant, O. (2017). Optimal market making. *Applied Mathematical Finance*, 24(2), 112–154.
  (arXiv:1605.01862)
- Guéant, O., Lehalle, C.-A. & Fernández-Tapia, J. (2013). Dealing with the inventory risk:
  a solution to the market making problem. *Mathematics and Financial Economics*, 7(4),
  477–507. (The ergodic closed form of Chapter 2 §3; the implementation error corrected in
  Contribution 17's addendum is an error of transcription, not of the paper.)
- Guilbaud, F. & Pham, H. (2013). Optimal high-frequency trading with limit and market orders.
  *Quantitative Finance*, 13(1), 79–94. (Spread as a discrete control; cited in Chapter 2 §5.)
- Ho, T. & Stoll, H. R. (1981). Optimal dealer pricing under transactions and return
  uncertainty. *Journal of Financial Economics*, 9(1), 47–73. (The dealer inventory-risk model
  A-S descends from.)
- Lehalle, C.-A. & Mounjid, O. (2017). Limit order strategic placement with adverse selection
  risk and the role of latency. *Market Microstructure and Liquidity*, 3(1). (arXiv:1610.00261)

## Adverse selection, information and the zero-profit condition

- Copeland, T. E. & Galai, D. (1983). Information effects on the bid–ask spread.
  *Journal of Finance*, 38(5), 1457–1469. (Dealer quotes as a written put plus call; the
  foundational "limit order = short option".)
- Easley, D., Kiefer, N. M., O'Hara, M. & Paperman, J. B. (1996). Liquidity, information, and
  infrequently traded stocks. *Journal of Finance*, 51(4), 1405–1436. (The PIN measure.
  Chapter 6 §7 estimates counterparty toxicity directly from wallet identity rather than
  inferring it from a trade-imbalance likelihood, and the comparison is made there.)
- Easley, D., López de Prado, M. & O'Hara, M. (2012). Flow toxicity and liquidity in a
  high-frequency world. *Review of Financial Studies*, 25(5), 1457–1493. (VPIN; the
  volume-clock successor to PIN, and the measure Contribution 21's filter implements.)
- Glosten, L. R. & Milgrom, P. R. (1985). Bid, ask and transaction prices in a specialist
  market with heterogeneously informed traders. *Journal of Financial Economics*, 14(1),
  71–100. (The zero-profit condition this thesis measures four ways.)
- Grossman, S. J. & Miller, M. H. (1988). Liquidity and market structure. *Journal of Finance*,
  43(3), 617–633. (Immediacy as a priced service; the 1/M competition term Part II turns on.)
- Hasbrouck, J. (1995). One security, many markets: determining the contributions to price
  discovery. *Journal of Finance*, 50(4), 1175–1199. (Information shares. Chapter 7's lead-lag
  matrix is a cruder time-domain instrument aimed at the same question, and §3's clock problem
  is why the finer method was not used.)
- Kyle, A. S. (1985). Continuous auctions and insider trading. *Econometrica*, 53(6),
  1315–1336. (The λ this thesis never estimates directly; Chapter 5 §7's breakeven ratio is a
  reduced-form statement of the same trade-off between depth and information.)
- Treynor, J. L. (as W. Bagehot) (1971). The only game in town. *Financial Analysts Journal*,
  27(2), 12–14. (Dealer versus informed trader.)

## Limit order books: structure, queues and ticks

- Bouchaud, J.-P., Bonart, J., Donier, J. & Gould, M. (2018). *Trades, Quotes and Prices:
  Financial Markets Under the Microscope*. Cambridge University Press. (Maker P&L, the
  short-volatility framing, the spread–volatility relation.)
- Cont, R., Kukanov, A. & Stoikov, S. (2014). The price impact of order book events.
  *Journal of Financial Econometrics*, 12(1), 47–88.
- Dayri, K. & Rosenbaum, M. (2015). Large tick assets: implicit spread and optimal tick size.
  *Market Microstructure and Liquidity*, 1(1), 1550003. (The large/small-tick distinction that
  organises Chapter 5 §7 and Chapter 6 §4.)
- Foucault, T., Pagano, M. & Röell, A. (2013). *Market Liquidity: Theory, Evidence, and Policy*.
  Oxford University Press. (The limit order as a free option.)
- Handa, P. & Schwartz, R. A. (1996). Limit order trading. *Journal of Finance*, 51(5),
  1835–1861.
- Hollifield, B., Miller, R. A. & Sandås, P. (2004). Empirical analysis of limit order markets.
  *Review of Economic Studies*, 71(4), 1027–1063.
- Lo, A. W., MacKinlay, A. C. & Zhang, J. (2002). Econometric models of limit-order executions.
  *Journal of Financial Economics*, 65(1), 31–71.
- Moallemi, C. C. & Yuan, K. (2017). A model for queue position valuation in a limit order
  book. Working paper, Columbia Business School. (The queue-position value Chapter 5 §2 finds
  the entire apparent profit consists of.)
- Smith, E., Farmer, J. D., Gillemot, L. & Krishnamurthy, S. (2003). Statistical theory of the
  continuous double auction. *Quantitative Finance*, 3(6), 481–514.
- Stoikov, S. (2018). The micro-price: a high-frequency estimator of future prices.
  *Quantitative Finance*, 18(12), 1959–1966. (The anchor Chapter 8 §6 adopts.)
- Wyart, M., Bouchaud, J.-P., Kockelkoren, J., Potters, M. & Vettorazzo, M. (2008). Relation
  between bid–ask spread, impact and volatility in order-driven markets. *Quantitative
  Finance*, 8(1), 41–57. (The spread–volatility equilibrium Chapter 5 §7 unifies with the
  queue-rent result.)

## High-frequency trading: empirics and market design

- Baron, M., Brogaard, J., Hagströmer, B. & Kirilenko, A. (2019). Risk and return in
  high-frequency trading. *Journal of Financial and Quantitative Analysis*, 54(3), 993–1024.
- Budish, E., Cramton, P. & Shim, J. (2015). The high-frequency trading arms race: frequent
  batch auctions as a market design response. *Quarterly Journal of Economics*, 130(4),
  1547–1621. (The speed race as a rent; Chapter 6 §5's speed instrument is its empirical
  counterpart on a book where the rent has already been competed to zero.)
- Menkveld, A. J. (2013). High frequency trading and the new market makers. *Journal of
  Financial Markets*, 16(4), 712–740.

## Machine learning and crypto microstructure

- Albers, J., Cucuringu, M., Howison, S. & Shestopaloff, A. Y. (2025). To make, or to take,
  that is the question: impact of LOB mechanics on natural trading strategies.
  arXiv:2502.18625. (A live trading experiment on the Binance BTC perpetual — the same venue
  and instrument class as Part I — identifying the "reversal" conditions under which a maker
  order carries positive expected return. The markout horizon convention of Chapter 6 §4
  follows this paper.)
- *Explainable patterns in cryptocurrency microstructure* (2026). arXiv:2602.00776.
  (Crypto-specific confirmation that imbalance predictability does not beat transaction costs.)
- Kearns, M. & Nevmyvaka, Y. (2013). Machine learning for market microstructure and high
  frequency trading. In *High Frequency Trading: New Realities for Traders, Markets and
  Regulators*. Risk Books.
- Kurth, J. G. et al. (2026). Is trend still your friend? A microstructural account of the
  demise of short-term trend-following. arXiv:2607.01550. (Volatility-normalised tick size as
  the cross-sectional survival variable; cited in Contribution 52's addendum and in further
  work.)
- Lalor, J. & Swishchuk, A. (2024). Market simulation under adverse selection.
  arXiv:2409.12721.
- Silantyev, E. (2019). Order flow analysis of cryptocurrency markets. *Digital Finance*,
  1(1), 191–218.
- Zhang, Z., Zohren, S. & Roberts, S. (2019). DeepLOB: deep convolutional neural networks for
  limit order books. *IEEE Transactions on Signal Processing*, 67(11), 3001–3012.

## Options and volatility

- Sinclair, E. (2013). *Volatility Trading* (2nd ed.). Wiley. (Short-gamma P&L: theta against
  gamma, realised against implied.)
- Taleb, N. N. (1997). *Dynamic Hedging: Managing Vanilla and Exotic Options*. Wiley.

## Dealer markets, historical

- Stoll, H. R. (1978). The supply of dealer services in securities markets. *Journal of
  Finance*, 33(4), 1133–1151.
