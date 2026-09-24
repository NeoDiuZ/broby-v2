/** Clinic calendar dates; never feed incomplete date-input values into React keys. */
export type CalendarView = 'Day' | 'Week' | 'Month';
export function dateString(date: Date): string {
 return `${String(date.getFullYear()).padStart(4, '0')}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
export function validCalendarDate(value: string): boolean {
 if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01' || value > '9999-12-31') return false;
 const date = new Date(value + 'T12:00:00');
 return Number.isFinite(date.getTime()) && dateString(date) === value;
}
export function calendarDays(value: string, view: CalendarView): string[] {
 if (!validCalendarDate(value)) return [];
 const start = new Date(value + 'T12:00:00');
 if (view === 'Month') start.setDate(1);
 if (view !== 'Day') start.setDate(start.getDate() - (start.getDay() + 6) % 7);
 return Array.from({length: view === 'Day' ? 1 : view === 'Week' ? 7 : 42}, (_, i) => {
  const day = new Date(start); day.setDate(day.getDate() + i); return dateString(day);
 }).filter(validCalendarDate);
}
export function shiftCalendar(value: string, view: CalendarView, direction: number): string {
 if (!validCalendarDate(value)) return value;
 const date = new Date(value + 'T12:00:00');
 if (view === 'Month') {
  const day = date.getDate(); date.setDate(1); date.setMonth(date.getMonth() + direction);
  const end = new Date(date); end.setMonth(end.getMonth() + 1); end.setDate(0);
  date.setDate(Math.min(day, end.getDate()));
 } else date.setDate(date.getDate() + direction * (view === 'Week' ? 7 : 1));
 const result = dateString(date); return validCalendarDate(result) ? result : value;
}
