"""Shared chart theme: light surface, dataviz-skill reference palette (validated categorical order)."""
import matplotlib
from matplotlib.colors import LinearSegmentedColormap
BG, FG, MUT, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e7e6e2"
BLUE, ORANGE, AQUA, YELLOW, MAGENTA = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"
NEUTRAL = "#9a9892"
ROLE_COL = {"top": ORANGE, "jungle": AQUA, "jng": AQUA, "mid": BLUE, "bottom": YELLOW, "bot": YELLOW, "support": MAGENTA, "sup": MAGENTA}
POS, NEG, MIDC = BLUE, ORANGE, NEUTRAL          # diverging pair for "better / worse than comparison"
SEQ = LinearSegmentedColormap.from_list("heat", ["#fdf0c9", "#f9c26b", "#f08a4b", "#d9482f", "#a1203a", "#5c1038"])  # pale gold -> orange -> deep wine (heatmap pattern)
def rc(plt):
    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": FG, "axes.labelcolor": MUT, "xtick.color": MUT, "ytick.color": MUT, "figure.facecolor": BG, "axes.facecolor": BG})
