"""Standalone publication plots; only compact computed frontier CSVs are read."""
from pathlib import Path
import sys

import pandas as pd

colors = {'2018_2021': '#126c8a', '2022_2023': '#d27337'}
order = {'NATIVE': 0, 'G25': 1, 'G50': 2, 'G75': 3, 'G100': 4}


def panel(ax, data, title):
    for period, frame in data.groupby('period'):
        frame = frame.assign(_order=frame.target.map(order)).sort_values('_order')
        x, y = frame.MaxDD*100, frame.CAGR*100
        ax.plot(x, y, '-o', color=colors[period], linewidth=1.7, markersize=4, label=period.replace('_', '–'))
        for row in frame.itertuples(index=False):
            ax.annotate(row.target.replace('NATIVE', 'N'), (row.MaxDD*100, row.CAGR*100),
                        xytext=(-5, 7 if period == '2018_2021' else -12), ha='right',
                        textcoords='offset points', fontsize=8, color=colors[period])
    ax.set_title(title, loc='left', fontweight='bold')
    ax.set_xlabel('Maximum drawdown (%)')
    ax.set_ylabel('CAGR (%)')
    ax.grid(alpha=.16)
    ax.margins(x=.18, y=.18)


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    root = Path(sys.argv[1])
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False, 'svg.hashsalt': 'five_strategy_capital_scaling_v1'})
    single = pd.read_csv(root/'output/single_strategy_scaling_frontier.csv')
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), layout='constrained')
    for ax, strategy in zip(axes.flat, ('ATRDR', 'MCB', 'OGR', 'IFCGR', 'SMV6')):
        panel(ax, single.loc[single.strategy.eq(strategy)], strategy)
    axes.flat[-1].axis('off')
    handles, labels = axes.flat[0].get_legend_handles_labels()
    axes.flat[-1].legend(handles, labels, loc='upper left', frameon=False)
    axes.flat[-1].text(.02, .62, 'Native → G25 → G50 → G75 → G100\n\nLive physical account; native exits\nNo leverage; no daily weight reset\nHistorical research, not authorization\nStock market capacity not modeled', va='top', linespacing=1.8, transform=axes.flat[-1].transAxes)
    fig.suptitle('Single-strategy capital frontiers', fontsize=17, fontweight='bold')
    for suffix in ('png', 'svg'):
        fig.savefig(root/f'reports/single_strategy_frontiers.{suffix}', dpi=170, metadata={'Date': None} if suffix == 'svg' else None)
    plt.close(fig)

    combined = pd.read_csv(root/'output/capital_scaling_frontier.csv')
    fig, axes = plt.subplots(2, 2, figsize=(12, 9), layout='constrained')
    for ax, (gap, mode) in zip(axes.flat, [('OGR', 'independent'), ('OGR', 'confirmation_tag'), ('IFCGR', 'independent'), ('IFCGR', 'confirmation_tag')]):
        panel(ax, combined.loc[combined.gap.eq(gap) & combined.mcb_mode.eq(mode)], f'{gap} / MCB {mode.replace("_", " ")}')
        ax.legend(frameon=False, fontsize=8)
    fig.suptitle('Combined capital frontiers · execution-aware', fontsize=17, fontweight='bold')
    for suffix in ('png', 'svg'):
        fig.savefig(root/f'reports/combined_frontiers.{suffix}', dpi=170, metadata={'Date': None} if suffix == 'svg' else None)
    plt.close(fig)


if __name__ == '__main__':
    main()
