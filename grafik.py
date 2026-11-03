import datetime as dt
import io
import os
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

from pc321_db import _connect
from tarif import band_for_hour

TZ = ZoneInfo("Asia/Tashkent")
STOP_W = float(os.environ.get("COMP_STOP_W", "10000"))
LOAD_W = float(os.environ.get("COMP_LOAD_W", "100000"))
GAP = 60          # soniya: undan katta uzilish = ma'lumot yo'q
WIN = 10          # daqiqa: tekislash oynasi
HIST_DAYS = 7     # odatdagi yo'lak uchun oldingi kunlar
MIN_EV = 10       # daqiqa: yo'lakdan shuncha vaqt chiqsa, o'zgarish
C_LOAD, C_IDLE, C_STOP, C_MISS = "#4caf6e", "#f0c93a", "#e05252", "#c9c9c9"


def dur(x):
    x = int(x)
    h, m = x // 3600, (x % 3600) // 60
    return f"{h} soat {m} daqiqa" if h else f"{m} daqiqa"


def money(x):
    return f"{x:,.0f}".replace(",", " ")


def smooth(sums, cnts):
    k = np.ones(WIN)
    s = np.convolve(sums, k, mode="same")
    c = np.convolve(cnts, k, mode="same")
    out = np.full(len(s), np.nan)
    ok = c >= 3
    out[ok] = s[ok] / c[ok]
    return out


def runs_of(mask, min_len):
    res, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if j - i + 1 >= min_len:
                res.append((i, j + 1))
            i = j + 1
        else:
            i += 1
    return res


def hodisa_images(arg=None):
    now = dt.datetime.now(TZ)
    try:
        day = dt.date.fromisoformat(arg) if arg else now.date()
    except ValueError:
        return []
    s = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
    e = s + dt.timedelta(days=1)
    base = s - dt.timedelta(days=HIST_DAYS)
    base_naive = base.replace(tzinfo=None)
    n_total = (HIST_DAYS + 1) * 1440
    sums = np.zeros(n_total)
    cnts = np.zeros(n_total)

    with _connect().cursor() as cur:
        cur.execute("""SELECT date_trunc('minute', ts AT TIME ZONE 'Asia/Tashkent'),
                              SUM(p_total), COUNT(p_total)
                       FROM readings WHERE ts >= %s AND ts < %s GROUP BY 1""", (base, e))
        for m, sm_, c in cur.fetchall():
            i = int((m - base_naive).total_seconds() // 60)
            if 0 <= i < n_total and sm_ is not None:
                sums[i] += float(sm_)
                cnts[i] += c
        cur.execute("SELECT ts, p_total FROM readings WHERE ts >= %s AND ts < %s ORDER BY ts", (s, e))
        rows = [(t.astimezone(TZ), float(w or 0)) for t, w in cur.fetchall()]
    if len(rows) < 2:
        return []

    sm = smooth(sums, cnts)
    cut = HIST_DAYS * 1440
    today_line = sm[cut:]
    hist = sm[:cut]
    hist = hist[~np.isnan(hist)]
    approx = len(hist) < 120
    ref = today_line[~np.isnan(today_line)] if approx else hist
    lo, hi = float(np.percentile(ref, 5)), float(np.percentile(ref, 95))

    # holatlar va soatbay ustunlar
    mins = [[0.0] * 24 for _ in range(3)]
    covered = [0.0] * 24
    tot = [0.0, 0.0, 0.0]
    idle_kwh = idle_cost = 0.0
    stops = []
    for (t0, w0), (t1, _) in zip(rows, rows[1:]):
        gap = (t1 - t0).total_seconds()
        if gap > GAP:
            continue
        st = 0 if w0 < STOP_W else (1 if w0 < LOAD_W else 2)
        h = t0.hour
        mins[st][h] += gap / 60
        covered[h] += gap / 60
        tot[st] += gap
        if st == 1:
            kwh = w0 * gap / 3.6e6
            idle_kwh += kwh
            idle_cost += kwh * band_for_hour(h)[1]
        if st == 0:
            if stops and stops[-1][1] == t0:
                stops[-1][1] = t1
            else:
                stops.append([t0, t1])
    stops = [x for x in stops if (x[1] - x[0]).total_seconds() >= 60]

    miss = [0.0] * 24
    for h in range(24):
        hs = s + dt.timedelta(hours=h)
        avail = (min(now, hs + dt.timedelta(hours=1)) - hs).total_seconds() / 60
        if avail > 0:
            miss[h] = max(avail - covered[h], 0)
            if miss[h] < 2:
                miss[h] = 0

    # o'zgarishlar: to'xtashlar + yo'lakdan chiqishlar
    events = [(a, b, "stop") for a, b in stops]
    mask = (today_line < lo * 0.97) | (today_line > hi * 1.03)
    for i, j in runs_of(mask, MIN_EV):
        a, b = s + dt.timedelta(minutes=i), s + dt.timedelta(minutes=j)
        if any(a < sb + dt.timedelta(minutes=WIN) and b > sa - dt.timedelta(minutes=WIN)
               for sa, sb in stops):
            continue
        up = np.nanmean(today_line[i:j]) > hi
        events.append((a, b, "up" if up else "down"))
    events.sort(key=lambda x: x[0])

    # chizish
    fig = plt.figure(figsize=(9, 11.5), dpi=100)
    gs = fig.add_gridspec(2, 1, left=0.09, right=0.97, top=0.83, bottom=0.17, hspace=0.5)
    ax1, ax2 = fig.add_subplot(gs[0]), fig.add_subplot(gs[1])

    word = "Bugun" if day == now.date() else "Shu kuni"
    fig.text(0.5, 0.965, f"Kompressor: {day}", ha="center", fontsize=18, fontweight="bold")
    if events:
        head, hc = f"{word} {len(events)} ta o'zgarish bo'ldi", "#d9822b"
    else:
        head, hc = "Hammasi odatdagidek", "#2e9e5b"
    fig.text(0.5, 0.915, head, ha="center", fontsize=22, fontweight="bold", color=hc)

    xs = [s + dt.timedelta(minutes=i) for i in range(1440)]
    ys = today_line / 1000
    ax1.fill_between([s, e], lo / 1000, hi / 1000, color=C_LOAD, alpha=0.18, lw=0)
    ax1.plot(xs, ys, color="#1f3b73", lw=2)
    col = {"stop": C_STOP, "up": "#e05252", "down": "#3b78d4"}
    txt = {"stop": "to'xtadi", "up": "quvvat ko'tarildi", "down": "quvvat pasaydi"}
    top = max(float(np.nanmax(ys)) if np.any(~np.isnan(ys)) else 0, hi / 1000)
    ymax = max(top * 1.55, 50)
    for k, (a, b, kind) in enumerate(events[:6]):
        ax1.axvspan(a, b, color=col[kind], alpha=0.35, lw=0)
        label = f"{a:%H:%M}-{b:%H:%M} {txt[kind]}" if kind == "stop" else f"{a:%H:%M} {txt[kind]}"
        mid = a + (b - a) / 2
        ha = "right" if mid > s + dt.timedelta(hours=18) else ("left" if mid < s + dt.timedelta(hours=5) else "center")
        ax1.annotate(label, xy=(mid, top * 1.05), xytext=(mid, ymax * (0.95 - 0.1 * (k % 4))),
                     ha=ha, fontsize=10, fontweight="bold",
                     bbox=dict(boxstyle="round,pad=0.25", fc="white", ec=col[kind]),
                     arrowprops=dict(arrowstyle="-", color=col[kind]))
    ax1.set_xlim(s, e)
    ax1.set_ylim(0, ymax)
    ax1.xaxis.set_major_locator(mdates.HourLocator(interval=3, tz=TZ))
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=TZ))
    ax1.set_ylabel("kVt")
    ax1.grid(True, alpha=0.3)
    ax1.set_title("Elektr quvvati (10 daqiqalik o'rtacha)", fontsize=12)
    ax1.legend(handles=[
        Line2D([0], [0], color="#1f3b73", lw=2, label="Quvvat"),
        Patch(color=C_LOAD, alpha=0.3, label="Odatdagi yo'lak"),
        Patch(color="#e05252", alpha=0.4, label="Ko'tarilish"),
        Patch(color="#3b78d4", alpha=0.4, label="Pasayish"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=4, frameon=False, fontsize=9)

    hrs = np.arange(24)
    l, i_, s_, m_ = (np.array(mins[2]), np.array(mins[1]), np.array(mins[0]), np.array(miss))
    ax2.bar(hrs, l, color=C_LOAD)
    ax2.bar(hrs, i_, bottom=l, color=C_IDLE)
    ax2.bar(hrs, s_, bottom=l + i_, color=C_STOP)
    ax2.bar(hrs, m_, bottom=l + i_ + s_, color=C_MISS)
    ax2.set_xlim(-0.6, 23.6)
    ax2.set_ylim(0, 60)
    ax2.set_xticks(hrs)
    ax2.set_xticklabels([f"{h:02d}" for h in hrs], fontsize=8)
    ax2.set_ylabel("daqiqa")
    ax2.set_title("Har soatda kompressor nima qilgan", fontsize=12)
    ax2.grid(True, axis="y", alpha=0.3)
    ax2.legend(handles=[
        Patch(color=C_LOAD, label="Havo berdi"),
        Patch(color=C_IDLE, label="Bo'sh aylandi"),
        Patch(color=C_STOP, label="To'xtadi"),
        Patch(color=C_MISS, label="Ma'lumot yo'q"),
    ], loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False, fontsize=9)

    lines = [f"Havo berdi: {dur(tot[2])}     Bo'sh aylandi: {dur(tot[1])}     To'xtadi: {dur(tot[0])}",
             f"Bo'sh aylanib taxminan {idle_kwh:.0f} kVt·soat elektr sarflagan: {money(idle_cost)} so'm"]
    if approx:
        lines.append("Odatdagi yo'lak shu kunning o'zidan olingan (taxminiy)")
    fig.text(0.5, 0.045, "\n".join(lines), ha="center", fontsize=10.5, linespacing=1.6)

    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    buf.name = "hodisalar.png"
    return [buf]
