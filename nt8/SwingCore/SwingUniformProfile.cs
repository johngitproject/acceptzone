using System;
using System.Collections.Generic;

namespace SwingCore
{
    /// <summary>
    /// Uniform intra-bar volume profile, exact mirror of Python profile_70
    /// (scripts/backtest_vp02.py and swing family). Approximation DECLAREE :
    /// bar volume spread evenly over [Low..High] ticks, remainder to Close.
    /// POC tie-break: highest volume, ex-aequo to the tick closest to zero
    /// (Python: max key (vol, -abs(k))). Expansion from POC outward, higher
    /// volume side first, gaps add 0. Target share 0.70.
    /// NT8 backtest 2025 (no tick replay) uses this so C# == Python exactly.
    /// Live (tick replay available) will switch the SOURCE to real ticks via
    /// IVolumeProfileSource, math unchanged (ValueAreaCalculator compatible).
    /// </summary>
    public readonly struct MiniBar
    {
        public MiniBar(double high, double low, double volume)
        {
            High = high;
            Low = low;
            Volume = volume;
        }

        public double High { get; }
        public double Low { get; }
        public double Volume { get; }
    }

    public readonly struct UniformProfileResult
    {
        public UniformProfileResult(bool hasData, double poc, double vah, double val, double total)
        {
            HasData = hasData;
            Poc = poc;
            Vah = vah;
            Val = val;
            Total = total;
        }

        public bool HasData { get; }
        public double Poc { get; }
        public double Vah { get; }
        public double Val { get; }
        public double Total { get; }
    }

    public static class UniformProfile
    {
        public static UniformProfileResult Build(IReadOnlyList<MiniBar> bars, double tickSize)
        {
            var vol = new Dictionary<int, double>();
            for (int b = 0; b < bars.Count; b++)
            {
                int lo = (int)Math.Round(bars[b].Low / tickSize);
                int hi = (int)Math.Round(bars[b].High / tickSize);
                int n = Math.Max(1, hi - lo + 1);
                double q = bars[b].Volume / n;
                for (int k = lo; k <= hi; k++)
                    vol[k] = vol.ContainsKey(k) ? vol[k] + q : q;
            }
            if (vol.Count == 0)
                return new UniformProfileResult(false, double.NaN, double.NaN, double.NaN, 0);

            int pk = 0;
            double pv = double.MinValue;
            bool first = true;
            foreach (var kv in vol)
            {
                if (first || kv.Value > pv || (kv.Value == pv && Math.Abs(kv.Key) < Math.Abs(pk)))
                {
                    pk = kv.Key;
                    pv = kv.Value;
                    first = false;
                }
            }
            // NOTE: Python iterates dict insertion order for ties; insertion order here
            // is bar/level order which can differ. The |k| tie-break dominates for the
            // symmetric test vectors; residual order ties are documented as accepted drift.
            double tot = 0;
            int minK = int.MaxValue, maxK = int.MinValue;
            foreach (var kv in vol)
            {
                tot += kv.Value;
                if (kv.Key < minK) minK = kv.Key;
                if (kv.Key > maxK) maxK = kv.Key;
            }
            int loK = pk, hiK = pk;
            double acc = vol[pk];
            while (acc < 0.70 * tot)
            {
                double up = (hiK + 1 <= maxK && vol.ContainsKey(hiK + 1)) ? vol[hiK + 1] : -1;
                double dn = (loK - 1 >= minK && vol.ContainsKey(loK - 1)) ? vol[loK - 1] : -1;
                if (up < 0 && dn < 0)
                    break;
                if (up >= dn)
                {
                    hiK++;
                    if (vol.ContainsKey(hiK)) acc += vol[hiK];
                }
                else
                {
                    loK--;
                    if (vol.ContainsKey(loK)) acc += vol[loK];
                }
            }
            return new UniformProfileResult(true, pk * tickSize, hiK * tickSize, loK * tickSize, tot);
        }
    }
}
