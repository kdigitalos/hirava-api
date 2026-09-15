"""Bounded attendance report calculations, preserving imported metric definitions."""
from collections import Counter
from datetime import datetime, time, timedelta

from fastapi import Depends, HTTPException, Response

from app.core.compatibility_routing import APIRouter
from app.data.database import get_db
from app.data.imported import table
from app.modules.workforce.imported_assets import admin, now, rows
from app.modules.workforce.imported_attendance import calendar_date
from app.modules.workforce.imported_attendance_views import attendance_window, day_status, days_between, leave_window, month_bounds, rounded

router = APIRouter(prefix='/api', tags=['HRMS attendance reports'])


def calculate_report(db, start_date, end_date, department_id):
    if not start_date or not end_date:
        today = now().date()
        start, end = month_bounds(today.year, today.month)
    else:
        start, end = calendar_date(start_date), calendar_date(end_date)
    length = (end - start).days + 1
    if not 1 <= length <= 366:
        raise HTTPException(422, 'Choose a date range of 1 to 366 days')
    tbl = table(db, 'Employee')
    criteria = [tbl.c.status == 'ACTIVE']
    if department_id:
        criteria.append(tbl.c.departmentId == department_id)
    employees = rows(db, 'Employee', *criteria)
    employee_ids = {e['id'] for e in employees}
    active = len(employees)
    departments = [{k: r[k] for k in ('id', 'name')} for r in rows(db, 'Department', order=table(db, 'Department').c.name)]
    records = [r for r in attendance_window(db, None, start, end) if r['employeeId'] in employee_ids]
    checked = {r['employeeId'] for r in records if r['checkIn']}
    overtime = sum(max(0, rounded((r['checkOut'] - r['checkIn']).total_seconds() / 3600, 1) - 8) for r in records if r['checkIn'] and r['checkOut'])
    leaves = leave_window(db, start, end)

    def period_metrics(lo, hi, attendance, leave, include_trend=False):
        indexed = {(r['employeeId'], r['workDate']): r for r in attendance}
        totals = Counter()
        numerator = denominator = 0
        trend = []
        for day in days_between(lo, hi):
            on_leave = {r['employeeId'] for r in leave if r['startDate'] <= day <= r['endDate']}
            counts = Counter()
            for employee in employees:
                record = indexed.get((employee['id'], day))
                state = day_status(employee['id'], record, on_leave)
                counts[state] += 1
                if state == 'PRESENT' and record['checkOut'] and record['checkOut'] < datetime.combine(day, time(17)):
                    totals['EARLY'] += 1
                else:
                    totals[state] += 1
            numerator += counts['PRESENT'] + counts['LATE']
            denominator += active - counts['ON_LEAVE']
            if include_trend:
                trend.append({'date': day.isoformat(), 'presentPct': rounded(100 * counts['PRESENT'] / (active or 1), 1),
                              'latePct': rounded(100 * counts['LATE'] / (active or 1), 1),
                              'absentPct': rounded(100 * (counts['ABSENT'] + counts['ON_LEAVE']) / (active or 1), 1)})
        return numerator, denominator, trend, totals

    num, den, trend, totals = period_metrics(start, end, records, leaves, True)
    previous_end, previous_start = start - timedelta(days=1), start - timedelta(days=length)
    p_num, p_den, _, _ = period_metrics(previous_start, previous_end,
        attendance_window(db, None, previous_start, previous_end), leave_window(db, previous_start, previous_end))
    average = rounded(100 * num / den, 1) if den else 0
    previous = 100 * p_num / p_den if p_den else average
    denominator = sum(totals.values()) or 1
    return {'startDate': start.isoformat(), 'endDate': end.isoformat(), 'departments': departments, 'trend': trend,
            'kpis': {'totalEmployeesLabel': 'Active Employees', 'totalEmployeesFraction': f'{len(checked)}/{active}',
                     'totalEmployeesNumerator': len(checked), 'totalEmployeesDenominator': active,
                     'averageAttendancePct': average, 'averageAttendanceDeltaPct': rounded(average - previous, 1),
                     'totalOvertimeHours': rounded(overtime, 1)},
            'distribution': {'presentPct': rounded(100 * totals['PRESENT'] / denominator, 1),
                             'latePct': rounded(100 * totals['LATE'] / denominator, 1),
                             'leaveEarlyPct': rounded(100 * (totals['EARLY'] + totals['ON_LEAVE']) / denominator, 1),
                             'absentPct': rounded(100 * totals['ABSENT'] / denominator, 1)}}


@router.get('/attendance-tracker/reports')
def report(startDate: str = '', endDate: str = '', departmentId: str = '', user=Depends(admin), db=Depends(get_db)):
    return calculate_report(db, startDate, endDate, departmentId)


def report_pdf(payload):
    from io import BytesIO
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=(612, 792), leftMargin=48, rightMargin=48,
                            topMargin=42, bottomMargin=42, title='Hirava attendance report', author='Hirava')
    styles = getSampleStyleSheet()
    styles['Title'].textColor = colors.HexColor('#322278')
    styles['Title'].fontSize = 19
    styles['Title'].leading = 24
    kpi, dist = payload['kpis'], payload['distribution']
    story = [Paragraph('HIRAVA - Time & Attendance Report', styles['Title']),
             Paragraph(f"Period: {payload['startDate']} to {payload['endDate']}", styles['Normal']), Spacer(1, 16),
             Paragraph('Summary', styles['Heading2'])]
    for line in [f"Employees with check-in / active employees: {kpi['totalEmployeesFraction']}",
                 f"Average attendance: {kpi['averageAttendancePct']:g}%",
                 f"Change versus prior period: {kpi['averageAttendanceDeltaPct']:+g}%",
                 f"Overtime: {kpi['totalOvertimeHours']:g} hours above 8 hours per day"]:
        story.append(Paragraph(line, styles['Normal']))
        story.append(Spacer(1, 4))
    story.extend([Spacer(1, 10), Paragraph('Status distribution (employee-days)', styles['Heading2'])])
    data = [['Present', 'Late', 'Early departure / leave', 'Absent'],
            [f"{dist[key]:g}%" for key in ('presentPct', 'latePct', 'leaveEarlyPct', 'absentPct')]]
    summary = Table(data, colWidths=[100, 90, 220, 106])
    styling = [('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#eeeafa')), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
               ('FONTSIZE', (0, 0), (-1, -1), 9), ('TOPPADDING', (0, 0), (-1, -1), 8), ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
               ('LINEBELOW', (0, 0), (-1, 0), 0.5, colors.HexColor('#c5bddf'))]
    summary.setStyle(TableStyle(styling))
    story.extend([summary, Spacer(1, 16), Paragraph('Daily trend', styles['Heading2'])])
    trend = [['Date', 'Present', 'Late', 'Absent / leave']] + [[r['date'], f"{r['presentPct']:g}%", f"{r['latePct']:g}%", f"{r['absentPct']:g}%"] for r in payload['trend']]
    detail = Table(trend, colWidths=[156, 110, 110, 140], repeatRows=1)
    detail.setStyle(TableStyle(styling + [('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7f7fb')])]))
    story.extend([detail, Spacer(1, 12), Paragraph('Calculated from saved attendance and approved leave. Calendar days and UTC clock thresholds follow the current attendance rules. This report does not authorize payroll or overtime payment.', styles['Normal'])])

    def footer(canvas, document):
        canvas.saveState()
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#666675'))
        canvas.drawString(48, 23, 'Hirava | Attendance')
        canvas.drawRightString(564, 23, f'Page {document.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return stream.getvalue()


@router.get('/attendance-tracker/reports/pdf')
def download_report(startDate: str = '', endDate: str = '', departmentId: str = '', user=Depends(admin), db=Depends(get_db)):
    payload = calculate_report(db, startDate, endDate, departmentId)
    filename = f"attendance-report-{payload['startDate']}-to-{payload['endDate']}.pdf"
    return Response(report_pdf(payload), media_type='application/pdf', headers={'Content-Disposition': f'attachment; filename="{filename}"'})
