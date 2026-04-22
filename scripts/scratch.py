import pandas as pd
from viz import load_view, plot_backtest_stacked, load_views

df = load_views("results/")
plot_backtest_stacked(df, view_rule='1s')
