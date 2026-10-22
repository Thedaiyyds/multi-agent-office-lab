// API date windows are half-open; people enter and read inclusive calendar dates.
export function shiftDate(value: string, days: number): string {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return "";
  const day = new Date(`${value}T00:00:00Z`);
  if (Number.isNaN(day.getTime())) return "";
  day.setUTCDate(day.getUTCDate() + days);
  return day.toISOString().slice(0, 10);
}
export const periodText = (start: string, end: string) =>
  `${start} 至 ${shiftDate(end, -1)}（含首尾日期）`;
export const metricValue = (value: number | null, unit: string) =>
  value === null
    ? "材料不足，暂不计算"
    : unit === "ratio"
      ? `${(value * 100).toFixed(2)}%`
      : Number(value.toFixed(2)).toString();
