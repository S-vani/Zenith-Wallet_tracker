// Shared chart helpers so the dashboard, holdings and search charts behave the same

export const TOOLTIP_STYLE = {
    background: "#0f1520",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: "0.625rem",
    fontSize: "0.8rem",
    color: "#f5f7ff",
};

export const CHART_UP = "#22c55e";
export const CHART_DOWN = "#ef4444";

// Avoids recharts' "width(-1) and height(-1)" warning on the first render
export const INITIAL_DIMENSION = {width: 1, height: 1};

// Hourly data over a week otherwise repeats the same date label several times; put one tick at the start of each day
export function dailyTicks(data, key = "time") {
    let lastDay = null;
    const ticks = [];
    for (const point of data) {
        const day = new Date(point[key]).toDateString();
        if (day !== lastDay) {
            ticks.push(point[key]);
            lastDay = day;
        }
    }
    return ticks;
}

// Intraday ranges show a time, longer ranges are daily candles so only the date is meaningful
export function tooltipDate(value, intraday) {
    return new Date(value).toLocaleString(undefined, intraday
        ? {month: "short", day: "numeric", hour: "numeric", minute: "2-digit"}
        : {month: "short", day: "numeric", year: "numeric"});
}
