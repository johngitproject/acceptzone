using System;
using System.Collections.Generic;

namespace SwingCore
{
    /// <summary>
    /// Daily RTH swing detection, exact mirror of the Python swing family
    /// (backtest_swing_v03 / s1 / v04): ATR20 = SMA(20) of True Range over
    /// RTH daily bars, swing candle when |Close-Open| &gt; 0.5 * ATR20.
    /// Bullish swing candle -&gt; Swing Low = day Low ; bearish -&gt; Swing High
    /// = day High. ATR uses the 20 sessions BEFORE the tested day (same as
    /// Python: atr[d] = mean of trs[-21:-1]). Pure, no NT8 dependency.
    /// </summary>
    public readonly struct DailyRthBar
    {
        public DailyRthBar(DateTime day, double open, double high, double low, double close)
        {
            Day = day.Date;
            Open = open;
            High = high;
            Low = low;
            Close = close;
        }

        public DateTime Day { get; }
        public double Open { get; }
        public double High { get; }
        public double Low { get; }
        public double Close { get; }
    }

    public readonly struct SwingMark
    {
        public SwingMark(DateTime day, bool isHigh, double price)
        {
            Day = day.Date;
            IsHigh = isHigh;
            Price = price;
        }

        public DateTime Day { get; }
        public bool IsHigh { get; }   // true = Swing High (bearish candle), false = Swing Low
        public double Price { get; }
        public string Side => IsHigh ? "high" : "low";
    }

    public sealed class SwingAtrEngine
    {
        public const int AtrPeriod = 20;
        public const double BodyRatio = 0.5;
        public const int LookbackDays = 20;

        private readonly List<double> _trs = new List<double>();
        private double? _prevClose;
        private readonly List<SwingMark> _swings = new List<SwingMark>();
        private readonly Dictionary<DateTime, double> _atrByDay = new Dictionary<DateTime, double>();

        public IReadOnlyList<SwingMark> Swings => _swings;
        public int SwingCount => _swings.Count;

        public double? Feed(DailyRthBar bar)
        {
            double tr = _prevClose.HasValue
                ? Math.Max(bar.High - bar.Low, Math.Max(Math.Abs(bar.High - _prevClose.Value), Math.Abs(bar.Low - _prevClose.Value)))
                : bar.High - bar.Low;
            _trs.Add(tr);
            double? atr = null;
            if (_trs.Count > AtrPeriod)
            {
                double sum = 0;
                for (int i = _trs.Count - AtrPeriod - 1; i < _trs.Count - 1; i++)
                    sum += _trs[i];
                atr = sum / AtrPeriod;
                _atrByDay[bar.Day] = atr.Value;
                double body = Math.Abs(bar.Close - bar.Open);
                if (body > BodyRatio * atr.Value)
                {
                    if (bar.Close > bar.Open)
                        _swings.Add(new SwingMark(bar.Day, false, bar.Low));
                    else if (bar.Close < bar.Open)
                        _swings.Add(new SwingMark(bar.Day, true, bar.High));
                    // doji (close == open) : no swing, same as Python (neither branch)
                }
            }
            _prevClose = bar.Close;
            return atr;
        }

        public bool TryGetAtr(DateTime day, out double atr) => _atrByDay.TryGetValue(day.Date, out atr);

        /// <summary>Swings strictly before day, within LookbackDays calendar days.</summary>
        public List<SwingMark> ActiveSwings(DateTime day, int lookbackDays = LookbackDays)
        {
            var d = day.Date;
            var out_ = new List<SwingMark>();
            foreach (var s in _swings)
            {
                if (s.Day < d && (d - s.Day).TotalDays <= lookbackDays)
                    out_.Add(s);
            }
            return out_;
        }
    }
}
