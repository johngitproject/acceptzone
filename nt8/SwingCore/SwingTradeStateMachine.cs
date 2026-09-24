using System;
using System.Collections.Generic;

namespace SwingCore
{
    /// <summary>
    /// Intraday accept/reject state machine, exact mirror of the Python v04
    /// process_intraday_level + find_candidates + POC gate + first-touch.
    /// Rules (locked): crossing required (prior close on the right side),
    /// entry proximity &lt;= 0.5*width + 8 ticks, POC gate binary
    /// (short only above POC+buf, long only below POC-buf, inside = skip),
    /// order T1 fade / T2 accept-flip (opposite direction) / T3 fresh signal,
    /// cooldown after exit, max attempts, done on target. Skips (POC/early)
    /// do not consume an attempt. Attempt 1 takes the first confirmed signal
    /// (fade or accept, like Python v04); attempt 2 requires the opposite
    /// kind (flip with direction change); attempt 3 takes the next fresh
    /// signal. Pure, no NT8 dependency. The live POC comes
    /// from a caller-supplied provider so backtest (prefix profile) and
    /// forward use the same code path.
    /// </summary>
    public readonly struct SigBar
    {
        public SigBar(long key, double open, double high, double low, double close)
        {
            Key = key;
            Open = open;
            High = high;
            Low = low;
            Close = close;
        }

        public long Key { get; }
        public double Open { get; }
        public double High { get; }
        public double Low { get; }
        public double Close { get; }
    }

    public readonly struct SignalCandidate
    {
        public SignalCandidate(string kind, int entryIdx, double extreme)
        {
            Kind = kind;
            EntryIdx = entryIdx;
            Extreme = extreme;
        }

        public string Kind { get; }   // "fade" | "accept"
        public int EntryIdx { get; }
        public double Extreme { get; }
    }

    public readonly struct TargetDef
    {
        public TargetDef(string name, double price)
        {
            Name = name;
            Price = price;
        }

        public string Name { get; }
        public double Price { get; }
    }

    public sealed class AttemptIntent
    {
        public int AttemptNo;
        public string Kind;           // "rejet" | "accept"
        public int Direction;         // +1 long, -1 short
        public int EntryIdx;
        public double Entry;
        public double Stop;
        public List<TargetDef> Targets = new List<TargetDef>();
        public int Flip;              // 1 when attempt 2 (direction flip)
        public string Prev;           // "none" | "stop" | "skip-poc" | "skip-early"
        public string PocPos;         // "above" | "below" | "inside" (vs live POC)
    }

    public static class SwingTradeStateMachine
    {
        public static List<SignalCandidate> FindCandidates(
            IReadOnlyList<SigBar> bars, double lvl, int biasDir,
            int accN, int rejWindow, double width, double tickSize,
            int bufTicks, int pokeTicks)
        {
            var out_ = new List<SignalCandidate>();
            double maxDist = 0.5 * Math.Max(width, tickSize) + 8 * tickSize;
            int n = bars.Count;
            int i = 0;
            while (i < n)
            {
                double prevClose = i == 0 ? bars[i].Open : bars[i - 1].Close;
                bool poked;
                if (biasDir == 1)
                {
                    if (!(prevClose < lvl + bufTicks * tickSize)) { i++; continue; }
                    poked = bars[i].High >= lvl + pokeTicks * tickSize;
                }
                else
                {
                    if (!(prevClose > lvl - bufTicks * tickSize)) { i++; continue; }
                    poked = bars[i].Low <= lvl - pokeTicks * tickSize;
                }
                if (!poked) { i++; continue; }
                double ext = biasDir == 1 ? bars[i].High : bars[i].Low;
                int run = 0;
                SignalCandidate? found = null;
                int jEnd = Math.Min(i + rejWindow + accN + 2, n);
                for (int j = i; j < jEnd; j++)
                {
                    double h2 = bars[j].High, l2 = bars[j].Low, c2 = bars[j].Close;
                    ext = biasDir == 1 ? Math.Max(ext, h2) : Math.Min(ext, l2);
                    bool beyond = biasDir == 1 ? c2 > lvl : c2 < lvl;
                    bool back = biasDir == 1 ? c2 < lvl : c2 > lvl;
                    if (back && (j - i) < rejWindow)
                    {
                        if (Math.Abs(c2 - lvl) <= maxDist)
                            found = new SignalCandidate("fade", j, ext);
                        break;
                    }
                    if (beyond)
                    {
                        run++;
                        if (run >= accN)
                        {
                            if (Math.Abs(c2 - lvl) <= maxDist)
                                found = new SignalCandidate("accept", j, ext);
                            break;
                        }
                    }
                    else run = 0;
                }
                if (found.HasValue)
                {
                    out_.Add(found.Value);
                    i = found.Value.EntryIdx + 1;
                }
                else i++;
            }
            return out_;
        }

        public static bool PocGate(double entry, double poc, int dir, int bufTicks, double tickSize)
        {
            if (dir == -1) return entry > poc + bufTicks * tickSize;
            return entry < poc - bufTicks * tickSize;
        }

        public static string PocPos(double entry, double poc, int bufTicks, double tickSize)
        {
            if (entry > poc + bufTicks * tickSize) return "above";
            if (entry < poc - bufTicks * tickSize) return "below";
            return "inside";
        }

        /// <summary>Conservative first touch, stop wins ties. Returns (res, idx).</summary>
        public static (string res, int idx) FirstTouch(
            IReadOnlyList<SigBar> bars, int start, double target, double stop, int dir)
        {
            for (int i = start; i < bars.Count; i++)
            {
                bool hitT = dir == 1 ? bars[i].High >= target : bars[i].Low <= target;
                bool hitS = dir == 1 ? bars[i].Low <= stop : bars[i].High >= stop;
                if (hitS && hitT) return ("stop", i);
                if (hitS) return ("stop", i);
                if (hitT) return ("target", i);
            }
            return ("eod", bars.Count - 1);
        }

        /// <summary>
        /// Full attempt loop for one level on one day-prefix of bars.
        /// zoneMode: fade targets use zonePoc/zoneVal/zoneVah; else live POC T1.
        /// livePoc(entryIdx) null = too-early skip (attempt not consumed).
        /// Returns intents in chronological order (each with 3 targets).
        /// </summary>
        public static List<AttemptIntent> ProcessLevel(
            IReadOnlyList<SigBar> bars, double lvl, int biasDir,
            int accN, int rejWindow, double width, double atr,
            double tickSize, int bufTicks, int pokeTicks,
            Func<int, double?> livePoc, bool zoneMode,
            double zonePoc, double zoneVal, double zoneVah,
            int cooldownBars, int maxAttempts,
            out int skipPoc, out int skipEarly)
        {
            var r = ProcessLevelEx(bars, lvl, biasDir, accN, rejWindow, width, atr,
                tickSize, bufTicks, pokeTicks, livePoc, zoneMode, zonePoc, zoneVal, zoneVah,
                cooldownBars, maxAttempts, out skipPoc, out skipEarly, out _);
            return r;
        }

        /// <summary>Same as ProcessLevel, plus per-skip entry indices (for newest-bar accounting).</summary>
        /// <param name="acceptSpan">Span for accept targets; NaN = max(width, atr).
        /// Zones (v04) pass max(zoneWidth, tick); swings pass atr.</param>
        public static List<AttemptIntent> ProcessLevelEx(
            IReadOnlyList<SigBar> bars, double lvl, int biasDir,
            int accN, int rejWindow, double width, double atr,
            double tickSize, int bufTicks, int pokeTicks,
            Func<int, double?> livePoc, bool zoneMode,
            double zonePoc, double zoneVal, double zoneVah,
            int cooldownBars, int maxAttempts,
            out int skipPoc, out int skipEarly, out List<int> skippedIdx,
            double acceptSpan = double.NaN)
        {
            skipPoc = 0;
            skipEarly = 0;
            skippedIdx = new List<int>();
            var intents = new List<AttemptIntent>();
            var cands = FindCandidates(bars, lvl, biasDir, accN, rejWindow, width, tickSize, bufTicks, pokeTicks);
            // Order: attempt 1 = first confirmed signal (any kind, like Python v04);
            // attempt 2 = first later signal of the OPPOSITE kind (flip, direction change);
            // attempt 3 = next fresh signal (any kind).
            int attempt = 0;
            string firstKind = null;
            string prev = "none";
            int prevExit = int.MinValue / 2;
            int ci = 0;
            while (attempt < maxAttempts && ci < cands.Count)
            {
                string want = attempt == 0 ? "any" : (attempt == 1 ? (firstKind == "fade" ? "accept" : "fade") : "any");
                SignalCandidate? pick = null;
                while (ci < cands.Count)
                {
                    var c = cands[ci++];
                    if (c.EntryIdx < prevExit + cooldownBars)
                        continue;
                    if (want != "any" && c.Kind != want)
                        continue;
                    pick = c;
                    break;
                }
                if (!pick.HasValue)
                    break;
                var p = pick.Value;
                double en = bars[p.EntryIdx].Close;
                double? live = livePoc(p.EntryIdx);
                if (!live.HasValue)
                {
                    prev = "skip-early";
                    prevExit = p.EntryIdx;
                    skipEarly++;
                    skippedIdx.Add(p.EntryIdx);
                    continue;
                }
                int dir = p.Kind == "fade" ? (biasDir == 1 ? -1 : 1) : (en > lvl ? 1 : -1);
                if (!PocGate(en, live.Value, dir, bufTicks, tickSize))
                {
                    prev = "skip-poc";
                    prevExit = p.EntryIdx;
                    skipPoc++;
                    skippedIdx.Add(p.EntryIdx);
                    continue;
                }
                attempt++;
                if (attempt == 1)
                    firstKind = p.Kind;
                var intent = new AttemptIntent
                {
                    AttemptNo = attempt,
                    Kind = p.Kind == "fade" ? "rejet" : "accept",
                    Direction = dir,
                    EntryIdx = p.EntryIdx,
                    Entry = en,
                    Flip = attempt == 2 ? 1 : 0,
                    Prev = prev,
                    PocPos = PocPos(en, live.Value, bufTicks, tickSize)
                };
                if (p.Kind == "fade")
                {
                    intent.Stop = dir == -1 ? p.Extreme + bufTicks * tickSize : p.Extreme - bufTicks * tickSize;
                    if (zoneMode)
                    {
                        intent.Targets.Add(new TargetDef("T1-poc", zonePoc));
                        intent.Targets.Add(new TargetDef("T2-w05", en + dir * 0.5 * Math.Max(width, tickSize)));
                        intent.Targets.Add(new TargetDef("T3-bord", dir == -1 ? zoneVal : zoneVah));
                    }
                    else
                    {
                        intent.Targets.Add(new TargetDef("T1-pocLIVE", live.Value));
                        intent.Targets.Add(new TargetDef("T2-a05", en + dir * 0.5 * atr));
                        intent.Targets.Add(new TargetDef("T3-opp", en + dir * 1.0 * atr));
                    }
                }
                else
                {
                    intent.Stop = dir == 1 ? lvl - bufTicks * tickSize : lvl + bufTicks * tickSize;
                    double span = double.IsNaN(acceptSpan) ? Math.Max(width, atr) : acceptSpan;
                    intent.Targets.Add(new TargetDef("T1-a05", en + dir * 0.5 * span));
                    intent.Targets.Add(new TargetDef("T2-a10", en + dir * 1.0 * span));
                    intent.Targets.Add(new TargetDef("T3-a15", en + dir * 1.5 * span));
                }
                intents.Add(intent);
                var refT = intent.Targets[1];
                var (res, idx) = FirstTouch(bars, p.EntryIdx, refT.Price, intent.Stop, dir);
                prevExit = idx;
                if (res == "target")
                    break;
                prev = res == "stop" ? "stop" : "eod";
                if (res == "eod")
                    break;
            }
            return intents;
        }
    }
}
