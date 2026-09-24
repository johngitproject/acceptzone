using System;

namespace SwingCore
{
    /// <summary>
    /// RTH session windowing WITHOUT any wall-clock / chart-timezone assumption.
    /// The chart MUST use an RTH template (e.g. CME US Index Futures RTH,
    /// Mon-Fri 08:30-15:15 Chicago); NT8 delimits sessions itself via
    /// Bars.IsFirstBarOfSession, which is correct in every chart timezone.
    /// Paris RTH 15h30-21h00 maps to fixed offsets inside the RTH session:
    /// normal weeks start at session bar 0 (08:30 CT), US/EU DST-mixed weeks
    /// start at session bar 60 (09:30 CT). Window = next 330 bars (5.5h).
    /// Mixed weeks detected by pure calendar date (US: 2nd Sun Mar -> 1st Sun
    /// Nov ; EU: last Sun Mar -> last Sun Oct), no timezone needed.
    /// 1H resample: first bucket 30 bars (08:30-09:00 / 09:30-10:00), then 60s
    /// (mirrors Python midnight-floor bins in both cases). 5m: groups of 5.
    /// </summary>
    public static class SwingRthSession
    {
        public const int WindowBars = 330;
        public const int MixedOffsetBars = 60;
        public const int RthGuardBars = 600;   // longer session => not an RTH template
        public const int MinLiveBars = 30;     // live-POC prefix minimum (mirror v04-live)

        public static DateTime NthWeekday(int year, int month, int n, DayOfWeek wd)
        {
            if (n > 0)
            {
                var d = new DateTime(year, month, 1);
                int off = ((int)wd - (int)d.DayOfWeek + 7) % 7;
                return d.AddDays(off + (n - 1) * 7);
            }
            DateTime last = month == 12
                ? new DateTime(year + 1, 1, 1).AddDays(-1)
                : new DateTime(year, month + 1, 1).AddDays(-1);
            int back = ((int)last.DayOfWeek - (int)wd + 7) % 7;
            return last.AddDays(-back);
        }

        public static DateTime LastSunday(int year, int month)
        {
            return NthWeekday(year, month, -1, DayOfWeek.Sunday);
        }

        public static bool IsUsDst(DateTime date)
        {
            DateTime d = date.Date;
            return d >= NthWeekday(d.Year, 3, 2, DayOfWeek.Sunday)
                && d < NthWeekday(d.Year, 11, 1, DayOfWeek.Sunday);
        }

        public static bool IsEuSummer(DateTime date)
        {
            DateTime d = date.Date;
            return d >= LastSunday(d.Year, 3) && d < LastSunday(d.Year, 10);
        }

        /// <summary>True on US/EU DST-mismatch weeks (Paris = 09:30-15:00 CT).</summary>
        public static bool IsMixedWeek(DateTime sessionDate)
        {
            return IsUsDst(sessionDate) != IsEuSummer(sessionDate);
        }

        public static int WindowOffsetBars(DateTime sessionDate)
        {
            return IsMixedWeek(sessionDate) ? MixedOffsetBars : 0;
        }

        /// <summary>Selected-bar count at end of resampled bucket (live-POC cutoff).</summary>
        public static int CutoffCount(int stepMin, int bucketIdx)
        {
            if (stepMin == 5)
                return 5 * (bucketIdx + 1);
            return 30 + bucketIdx * 60; // 1H: first bucket 30, then 60s
        }

        /// <summary>Closed-bucket count available from n selected bars.</summary>
        public static int ClosedBuckets(int stepMin, int selectedCount)
        {
            if (stepMin == 5)
                return selectedCount / 5;
            if (selectedCount < 30)
                return 0;
            return 1 + (selectedCount - 30) / 60;
        }
    }
}
