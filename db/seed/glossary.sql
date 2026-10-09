-- Glossary for the AI analyst's lookup_glossary tool: 30 vetted, plain-English definitions.
-- Idempotent: re-running updates the text. Apply after migration 005:
--   Supabase SQL Editor (paste and run), or psql -f db/seed/glossary.sql
-- Educational definitions only; no advice. Edit wording here, never in the database.

INSERT INTO public.glossary (term, aliases, definition, category) VALUES
('market regime', '{regime,regimes}', 'A period in which the market behaves in a broadly similar way, for example calm and rising, choppy, or falling sharply with high fear. MarketMood estimates the current regime from price and volatility data; it describes conditions, it does not predict prices.', 'marketmood'),
('bull regime', '{bull,bullish,bull market}', 'In MarketMood, a calm market where prices have been rising and volatility is low. More generally, a bull market is a long period of rising prices, often described as a rise of 20% or more from a low.', 'marketmood'),
('sideways regime', '{sideways,range-bound,choppy market}', 'In MarketMood, a market without a clear trend: prices move up and down within a range and volatility is normal. Many long stretches of history look like this.', 'marketmood'),
('crisis regime', '{crisis,market crisis,stress}', 'In MarketMood, a stressed market: prices have fallen, daily swings are large and India VIX is high. The March 2020 COVID crash is the clearest example in our data.', 'marketmood'),
('bear market', '{bear,bearish}', 'A long period of falling prices, often described as a fall of 20% or more from a recent high. MarketMood does not use this label; its stressed state is called Crisis.', 'markets'),
('correction', '{market correction}', 'A fall of roughly 10% or more from a recent high, usually shorter and milder than a bear market. Corrections happen regularly, even within long rising periods.', 'markets'),
('nifty 50', '{nifty,nifty50,^nsei}', 'An index of 50 large companies listed on the National Stock Exchange of India, weighted by the value of their freely traded shares. It is widely used as a summary of the Indian stock market.', 'markets'),
('india vix', '{vix,volatility index,fear index}', 'The National Stock Exchange''s volatility index. It is calculated from NIFTY option prices and shows how much movement the market expects over the next 30 days, as an annual percentage. Higher values mean more expected turbulence.', 'markets'),
('volatility', '{volatility_20d,risk}', 'How much prices move up and down. MarketMood measures it as the standard deviation of daily returns over the last 20 trading days. Higher volatility means bigger daily swings in both directions.', 'features'),
('drawdown', '{drawdown_60d,max drawdown}', 'How far the price is below its recent peak, as a percentage. MarketMood uses the highest close of the last 60 trading days; a drawdown of -10% means NIFTY is 10% below that peak.', 'features'),
('sharpe ratio', '{sharpe_60d,risk-adjusted return}', 'Return divided by volatility, a measure of how much gain came per unit of risk. MarketMood uses the average daily return over 60 trading days divided by its standard deviation; positive means prices have tended to rise.', 'features'),
('autocorrelation', '{autocorr_lag1,trendiness}', 'Whether one day''s return tends to be followed by a similar return the next day. Positive values suggest trending behaviour, negative values suggest back-and-forth moves. MarketMood uses a 30-day window.', 'features'),
('skewness', '{skewness_30d,skew}', 'Whether recent returns lean to one side. Negative skewness means occasional large falls compared with the usual gains, a sign of crash risk. MarketMood uses the last 30 trading days.', 'features'),
('bollinger bands', '{bb_width,band width}', 'Lines drawn two standard deviations above and below a 20-day moving average of the price. The width between them, relative to the average, is a simple measure of how volatile the market has been.', 'features'),
('vix change', '{vix_change_30d}', 'The percentage change in India VIX over the last 30 trading days. A sharp rise means fear is building; a fall means the market is calming down.', 'features'),
('moving average', '{sma,ema}', 'The average price over a fixed number of recent days, recalculated each day. It smooths out daily noise so the underlying direction is easier to see.', 'markets'),
('hidden markov model', '{hmm,model}', 'A statistical model that assumes the market moves between a few hidden states (here Bull, Sideways and Crisis) and estimates the chance of each state from what is observed each day. MarketMood uses only data up to each day, never later data.', 'marketmood'),
('confidence', '{probability,model confidence}', 'The model''s own probability for the regime it shows. It is a measure of how clearly the data fits that regime, not a guarantee, and models like this tend to be overconfident.', 'marketmood'),
('sip', '{systematic investment plan}', 'A Systematic Investment Plan: investing a fixed amount at regular intervals, usually monthly, in a mutual fund. Because the amount is fixed, more units are bought when prices are low and fewer when they are high.', 'investing'),
('mutual fund', '{mf,fund}', 'A pooled investment managed by a professional fund house. Many investors put money together and the fund buys a portfolio of shares, bonds or both, according to its stated objective.', 'investing'),
('index fund', '{index funds,nifty index fund}', 'A mutual fund or ETF that tries to match an index, such as NIFTY 50, by holding the same companies in the same proportions. It does not try to beat the market, which keeps costs low.', 'investing'),
('etf', '{exchange traded fund}', 'An exchange-traded fund: a fund whose units trade on the stock exchange like shares during market hours. Many ETFs track an index such as NIFTY 50.', 'investing'),
('diversification', '{diversify}', 'Spreading money across different investments, sectors or asset types so that one bad outcome does not dominate the result. It reduces risk but does not remove it.', 'investing'),
('asset allocation', '{allocation}', 'How an investment portfolio is divided between asset types such as equity, debt and cash. It is usually chosen to fit a person''s goals, time horizon and risk tolerance.', 'investing'),
('rebalancing', '{rebalance}', 'Bringing a portfolio back to its intended mix, for example selling some equity after a rise or adding to it after a fall, so the level of risk stays where it was planned.', 'investing'),
('risk tolerance', '{risk appetite}', 'How much short-term loss or uncertainty a person can accept, financially and emotionally, while pursuing their goals. It differs from person to person and changes over time.', 'investing'),
('cagr', '{compound annual growth rate}', 'Compound annual growth rate: the steady yearly rate that would turn a starting value into an ending value over a period. It smooths out the ups and downs along the way.', 'investing'),
('fii', '{fpi,foreign institutional investors,foreign portfolio investors}', 'Foreign institutional or portfolio investors: overseas funds that buy and sell Indian shares and bonds. Their flows can move the market. MarketMood does not yet use FII data.', 'markets'),
('dii', '{domestic institutional investors}', 'Domestic institutional investors such as Indian mutual funds, insurance companies and pension funds. Their buying and selling often balances foreign flows.', 'markets'),
('sebi', '{securities and exchange board of india,sebi registered adviser,registered investment adviser}', 'The Securities and Exchange Board of India, the market regulator. For personal investment advice, consult a SEBI-registered investment adviser; MarketMood is educational and does not give advice.', 'regulation')
ON CONFLICT (term) DO UPDATE SET
    aliases = EXCLUDED.aliases,
    definition = EXCLUDED.definition,
    category = EXCLUDED.category;
