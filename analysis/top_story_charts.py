"""X-ready charts: the top laner's lead matters least.  python3 analysis/top_story_charts.py [data_dir] [out_dir]"""
import json, sys
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm
ROOT=Path(__file__).resolve().parent.parent if "analysis" in str(Path(__file__).resolve()) else Path(".")
DATA=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/"data/processed"
OUT=Path(sys.argv[2]) if len(sys.argv)>2 else ROOT/"charts"; OUT.mkdir(parents=True,exist_ok=True)
for f in ("Liberation Sans","Helvetica Neue","Arial","DejaVu Sans"):
    if any(f==x.name for x in fm.fontManager.ttflist): plt.rcParams["font.family"]=f; break
BG,INK,INK2,MUT,GRID="#f5f6f7","#1b2128","#4a5560","#8d96a2","#dfe3e7"
TOP,OTH="#2a78d6","#8d96a2"
ROLES=["top","jng","mid","bot","sup"]; NAMES=["Top","Jungle","Mid","ADC","Support"]
roles=json.load(open(DATA/"top_story_roles.json")); teams=json.load(open(DATA/"top_story_teams.json"))
SRC="Source: Oracle's Elixir, 2026 pro games from 9 leagues and international events (LPL, LCK, LEC, LCS, LCP, CBLOL, First Stand, MSI, EWC), no Worlds games. Association, not cause."
def frame(title,sub,foot,h=4.5,tl=1):
    fig=plt.figure(figsize=(8,h),dpi=200,facecolor=BG)
    fig.text(.04,.935,title,fontsize=17,fontweight="bold",color=INK,va="top",wrap=True)
    fig.text(.04,.935-(.075 if tl==1 else .13)*(4.5/h)-.03,sub,fontsize=10.5,color=INK2,va="top")
    fig.text(.04,.03,foot,fontsize=6.6,color=MUT,va="bottom",wrap=True)
    return fig
def style(ax):
    ax.set_facecolor(BG)
    for s in ("top","right","left"): ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID); ax.tick_params(length=0,colors=INK2,labelsize=9)
def bars(ax,d,xmax,fmt=lambda v:f"{v*100:.0f}%",small=50,xmin=0,shown_n=True):
    for i,(r,nm) in enumerate(zip(ROLES,NAMES)):
        x=d[r]; c=TOP if r=="top" else OTH; y=len(ROLES)-1-i; thin=x["n"]<small
        ax.barh(y,x["rate"]-xmin,left=xmin,height=.62,color=BG if thin else c,edgecolor=c,linewidth=1.4 if thin else 0,hatch="////" if thin else None,zorder=2)
        ax.plot([x["lo"],x["hi"]],[y,y],color=INK,lw=1.1,zorder=3,solid_capstyle="butt")
        for e in (x["lo"],x["hi"]): ax.plot([e,e],[y-.1,y+.1],color=INK,lw=1.1,zorder=3)
        ax.text(x["hi"]+.012,y,f"{fmt(x['rate'])}",va="center",fontsize=12,fontweight="bold" if r=="top" else "normal",color=TOP if r=="top" else INK)
        if shown_n: ax.text(-0.012,y-.30,f"{x['n']:,} cases"+(" (few)" if thin else ""),va="center",ha="right",fontsize=7,color=MUT,transform=ax.get_yaxis_transform())
    ax.set_yticks(range(len(ROLES))); ax.set_yticklabels(NAMES[::-1],fontsize=11)
    for t in ax.get_yticklabels():
        if t.get_text()=="Top": t.set_color(TOP); t.set_fontweight("bold")
    ax.set_xlim(xmin,xmax); ax.set_ylim(-.6,4.6)
    ax.xaxis.set_major_formatter(lambda v,p:f"{v*100:.0f}%"); ax.grid(axis="x",color=GRID,lw=.8,zorder=0)
    style(ax)
n=roles["n_games"]
# 1 hero
a=roles["ahead_1000"]
fig=frame("A top laner 1,000 gold ahead still loses 1 game in 3",
  "Share of games won by a team whose laner was 1,000+ gold ahead of his lane opponent at 15 minutes.\nEvery other role turns that lead into a win 78% to 86% of the time. Bars show win rate; whiskers the 90% range.",
  SRC+f" {n:,} games, two sides each. Hatched bar: fewer than 100 cases.")
ax=fig.add_axes([.14,.13,.80,.56]); bars(ax,a,1.0,small=100,xmin=0.4); ax.set_xlim(.4,1.0)
fig.savefig(OUT/"top_story_1_ahead.png",facecolor=BG); plt.close(fig)
# 2 tug of war (two panels)
fig=frame("Win your lane, lose your team? Win your team, lose your lane?",
  "One laner is 500+ gold ahead (or behind) at 15 minutes while his four teammates are 1,000+ gold\nbehind (or ahead) combined. How often does the team win? The top lane is overruled the most.",
  SRC+" Hatched bar: fewer than 100 cases. Case counts are the same in both panels.",tl=1)
for k,(key,ttl,xl) in enumerate([("tug_top_ahead_team_behind","Laner ahead, teammates behind: team wins",(.2,.6)),("tug_top_behind_team_ahead","Laner behind, teammates ahead: team wins",(.4,.95))]):
    ax=fig.add_axes([.14+k*.44,.13,.35,.50]); bars(ax,roles[key],xl[1],small=100,xmin=xl[0],shown_n=(k==0)); ax.set_xlim(*xl)
    ax.set_title(ttl,fontsize=9.5,color=INK,loc="left",pad=8,fontweight="bold")
    if k==1: ax.set_yticklabels([]); 
    for t in ax.texts:
        if "cases" in t.get_text(): t.set_fontsize(6.2)
fig.savefig(OUT/"top_story_2_tug_of_war.png",facecolor=BG); plt.close(fig)
# 3 kill participation
kp=roles["kill_participation"]
fig=frame("The top laner takes part in the fewest of his team's kills",
  "Average share of his team's kills that each role took part in (kills + assists, divided by team kills), all 2026 games.\nTop laners are in about half. Every other role is 13 to 22 points higher.",SRC)
ax=fig.add_axes([.14,.13,.80,.56])
for i,(r,nm) in enumerate(zip(ROLES,NAMES)):
    y=4-i; v=kp[r]["mean"]; c=TOP if r=="top" else OTH
    ax.barh(y,v,height=.62,color=c,zorder=2)
    ax.text(v+.012,y,f"{v*100:.0f}%",va="center",fontsize=12,fontweight="bold" if r=="top" else "normal",color=TOP if r=="top" else INK)
ax.set_yticks(range(5)); ax.set_yticklabels(NAMES[::-1],fontsize=11)
for t in ax.get_yticklabels():
    if t.get_text()=="Top": t.set_color(TOP); t.set_fontweight("bold")
ax.set_xlim(0,.85); ax.set_ylim(-.6,4.6); ax.xaxis.set_major_formatter(lambda v,p:f"{v*100:.0f}%"); ax.grid(axis="x",color=GRID,lw=.8,zorder=0); style(ax)
fig.savefig(OUT/"top_story_3_kill_participation.png",facecolor=BG); plt.close(fig)
# 4 teams
T=sorted(teams,key=lambda t:t["diff"]); nT=len(T)
fig=frame("In 14 of 15 Worlds teams, the top lane matters less\nto winning than the other four roles",
  "For each team's current top laner: win rate when ahead at 15 minutes minus win rate when behind, in points.\nBlue dot: the top laner (line: 90% range). Grey diamond: the average of his four teammates in the same games.",
  "Source: Oracle's Elixir, 2026 games, no Worlds games. Current top laner of each team, all his 2026 games (pooled across teams where he moved). Hollow dot: under 50 games. Shaded rows: the gap to teammates is clear (90% range excludes zero). Association, not cause.",h=5.6,tl=2)
ax=fig.add_axes([.17,.14,.78,.58]); style(ax)
for i,t in enumerate(T):
    y=nT-1-i; thin=t["n"]<50
    if t["diff_hi"]<0: ax.axhspan(y-.5,y+.5,color="#e8eef7",zorder=0)
    ax.plot([t["top_lo"]*100,t["top_hi"]*100],[y,y],color=TOP,lw=1.6,alpha=.55,solid_capstyle="round",zorder=2)
    ax.plot([t["swing_top"]*100,t["swing_oth"]*100],[y,y],color=MUT,lw=.8,zorder=1,ls=":")
    ax.scatter(t["swing_oth"]*100,y,marker="D",s=34,color=OTH,zorder=3)
    ax.scatter(t["swing_top"]*100,y,s=70,color=BG if thin else TOP,edgecolor=TOP,linewidth=1.8,zorder=4)
    ax.text(-67,y+.16,t["team"],ha="right",va="center",fontsize=10,fontweight="bold",color=INK)
    ax.text(-67,y-.24,f"{t['n']} games",ha="right",va="center",fontsize=6.4,color=MUT)
ax.axvline(0,color=INK2,lw=.9,zorder=1)
ax.set_ylim(-.7,nT-.3); ax.set_xlim(-65,55); ax.set_yticks([]); ax.set_xticks([-60,-40,-20,0,20,40]); ax.set_xticklabels(["-60","-40","-20","0","+20","+40"])
ax.grid(axis="x",color=GRID,lw=.8,zorder=0); ax.set_xlabel("How much more a team wins when this lane is ahead (percentage points)",fontsize=8,color=INK2,labelpad=4)
fig.savefig(OUT/"top_story_4_teams.png",facecolor=BG); plt.close(fig)
print("ok")
