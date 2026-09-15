"""Generate synthetic PDF layout fixtures; never reads business records."""
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.modules.workforce.imported_attendance_reports import report_pdf

directory = Path(__file__).resolve().parents[1] / 'test-output' / 'attendance-pdf'
directory.mkdir(parents=True, exist_ok=True)
payload = {'startDate': '2026-01-01', 'endDate': '2026-12-31',
           'kpis': {'totalEmployeesFraction': '125/150', 'averageAttendancePct': 83.3, 'averageAttendanceDeltaPct': -1.2, 'totalOvertimeHours': 124.5},
           'distribution': {'presentPct': 70, 'latePct': 13.3, 'leaveEarlyPct': 6.7, 'absentPct': 10},
           'trend': [{'date': (date(2026, 1, 1) + timedelta(days=i)).isoformat(), 'presentPct': 70, 'latePct': 13.3, 'absentPct': 16.7} for i in range(365)]}
path = directory / 'synthetic-attendance-report.pdf'
path.write_bytes(report_pdf(payload))
print(path)
