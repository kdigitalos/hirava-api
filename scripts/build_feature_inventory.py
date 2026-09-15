"""Build a source inventory for consolidation. Reads code only; never connects to DB."""
import ast
import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'consolidation'
PRISMA = ROOT / 'migrations/imported/schema.prisma'

# Model-level destinations are design targets, not executable migration mappings.
GROUPS = [
    ('identity', 'User PartyUserRole Role Module RoleModule OrganizationRoleSetting', 'users + explicit role grants and module entitlements', 'Merge authorization; verified subject links only; role definitions do not grant access.'),
    ('organization', 'Department Designation Branch JobTitle OrganizationCompanyProfile', 'organization_units + positions + job profiles/company/location extensions', 'Keep designation/job title separate from an approved position; preserve hierarchy and effective dates.'),
    ('workforce', 'Employee EmployeeProfile', 'workers + employments + restricted profile extensions', 'Split person and employment fields; preserve payroll/profile fields with field access; no email-only linking.'),
    ('lifecycle', 'EmployeeLifecycleEvent EmployeeTask OnboardingCandidate ExitRequest', 'lifecycle_cases + tasks + lifecycle events', 'Preserve statuses, assignees and histories; prehire is not active employment.'),
    ('templates', 'OnboardingGroup OnboardingTemplate ExitOffboardingTemplate', 'versioned lifecycle templates and groups', 'Port existing unique capability; template application must be repeat-safe.'),
    ('probation', 'ProbationRecord ProbationPolicySettings', 'probation records and policy versions', 'Port unique capability; human review and effective dates.'),
    ('leave', 'LeaveType LeaveBalance LeaveRequest PublicHoliday', 'leave_types + leave_balances + leave_requests + holiday calendars', 'Merge leave implementations; map units, half days, year boundaries and existing approval evidence explicitly.'),
    ('assets', 'AssetCategory AssetVendor AssetPhoto Asset AssetAssignment AssetReturnRequest LostDamageIncident LostDamagePolicyGuideline LostDamageWorkflowStep', 'asset domain under FastAPI', 'Port unique inventory, assignment, return and incident behavior; link canonical worker/employment IDs.'),
    ('attendance', 'AttendancePolicy AttendanceRecord EmployeeShift', 'attendance domain under FastAPI', 'Retain basic attendance/shifts; do not infer a full payroll or shift optimization engine.'),
    ('settlements', 'FnfSettlement', 'exit settlement records under FastAPI', 'Preserve recorded settlement details; not a statutory payroll engine.'),
    ('documents', 'EmployeeDocument', 'documents + domain link/review/expiry extensions', 'One storage service; preserve object keys, owner scope, review status and expiry.'),
    ('policies', 'PrivacyPolicy', 'policies + versions + policy_acknowledgements', 'Merge policy content with audience/effective-date/acknowledgement behavior.'),
    ('hr-service', 'SupportTicket', 'hr_cases + case_notes + routing/SLA fields', 'Merge ticket and case experience; confidential notes stay separately restricted.'),
    ('knowledge', 'KnowledgeBaseArticle KnowledgeBaseFaq', 'knowledge articles and FAQs', 'Port unique content; publish state and audience must govern search and AI.'),
    ('performance', 'PerformanceFeedback PerformanceGoal PerformanceAppraisal', 'performance_goals + performance_reviews + feedback/cycle extensions', 'Merge goals/reviews; retain weights, targets and reflections without automatic employment decisions.'),
    ('self-service', 'EmployeeSelfServiceRequest', 'profile_changes + typed self-service requests', 'Extend beyond native name changes; map proposed fields and decision history, never auto-approve on import.'),
    ('communications', 'Announcement AdminScheduleItem RmsTemplate', 'announcements + schedule items + message templates', 'Preserve distinct records; reuse shared notification/outbox delivery.'),
    ('requisitions', 'JobOpening RmsJobOpening', 'requisitions + job publications', 'Two mixed job stores map to one requisition domain; employee jobs are a publication view, not a second vacancy.'),
    ('applications', 'JobApplication RmsCandidate RmsCandidateFormDetail', 'candidates + applications + form submissions', 'RmsCandidate is job-bound: split person from application; ambiguous matches require review; preserve JSON fields.'),
    ('referrals', 'JobReferral', 'referrals linked to canonical applications', 'Keep referral provenance and referrer access; referral is not another candidate master.'),
    ('recruiting-config', 'RmsSectionValue RmsHiringFlow RmsQuestion', 'versioned recruiting forms/stages/questions', 'Preserve custom fields and questions; map free-text status values explicitly.'),
    ('interviews', 'RmsInterview RmsInterviewSchedule', 'interviews + participants + scheduling history', 'One interview identity, multiple rounds/slots; preserve timezone and panel membership; no string-based access checks.'),
    ('scorecards', 'RmsFeedback', 'scorecards + competency responses', 'Retain recommendations and round-specific feedback; map authors to verified users.'),
    ('saas', 'ClientSubscriptionRequest', 'subscription enquiry and manual plan administration', 'Keep lead capture separate from active paid entitlements; no payment integration assumed.'),
    ('parties', 'Party PartyRole PartyContactPerson PartyAddress PartyBankDetail', 'party domain with explicit identity reference where applicable', 'Preserve business contacts/addresses/bank records; PartyRole is a business relationship, not an authorization grant.'),
]


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = {}
    for domain, names, target, rule in GROUPS:
        for name in names.split():
            assert name not in mapping, name
            mapping[name] = (domain, target, rule)
    source = PRISMA.read_text(encoding='utf-8')
    tables, details = [], []
    for match in re.finditer(r'^model (\w+) \{\n(.*?)^\}', source, re.M | re.S):
        name, body = match.groups()
        sql_name = re.search(r'@@map\("([^"]+)"\)', body)
        table = sql_name.group(1) if sql_name else name
        domain, target, rule = mapping.pop(name)
        tables.append(dict(source_schema='public', source_table=table, source_model=name,
                           owner=domain, action='Merge/extend' if domain in {
                               'identity','organization','workforce','lifecycle','leave','documents',
                               'policies','hr-service','performance','self-service','requisitions',
                               'applications','interviews','scorecards'} else 'Port unique capability',
                           target=target, mapping_rule=rule, migration_status='Read-only canonical view installed' if name in {'JobOpening', 'RmsJobOpening'} else 'Not executed'))
        details.append(dict(schema='public', table=table, model=name,
                            source='migrations/imported/schema.prisma',
                            line=source[:match.start()].count('\n') + 1,
                            definition=body.strip()))
    assert not mapping, f'Unknown mapped models: {mapping}'
    for file in sorted((ROOT / 'app').rglob('models.py')):
        tree = ast.parse(file.read_text(encoding='utf-8-sig'))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = next((stmt.value.value for stmt in node.body
                          if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant)
                          and any(isinstance(t, ast.Name) and t.id == '__tablename__' for t in stmt.targets)), None)
            if not table:
                continue
            rel = file.relative_to(ROOT).as_posix()
            tables.append(dict(source_schema='hirava_core', source_table=table, source_model=node.name,
                               owner=file.parent.name, action='Retain and extend',
                               target=table, mapping_rule='Keep native invariants; extend fields and relationships before importing overlapping source data.',
                               migration_status='No consolidation executed'))
            details.append(dict(schema='hirava_core', table=table, model=node.name, source=rel,
                                line=node.lineno, definition=ast.get_source_segment(file.read_text(encoding='utf-8-sig'), node)))
    with (OUT / 'database-map.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(tables[0]))
        writer.writeheader()
        writer.writerows(tables)
    (OUT / 'model-inventory.json').write_text(json.dumps(details, indent=2), encoding='utf-8')

    pages = ROOT.parent / 'hirava-webapp/src/app'
    routes = []
    for file in sorted(pages.rglob('*')):
        if file.name not in {'page.tsx', 'route.ts'}:
            continue
        text = file.read_text(encoding='utf-8-sig')
        rel = file.relative_to(pages).as_posix()
        routes.append(dict(source_path=rel, kind='page' if file.name == 'page.tsx' else 'route',
                           methods=re.findall(r'^export (?:async )?function (GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\b', text, re.M),
                           has_demo_marker=bool(re.search(r'\b(mock|demo data|placeholder data)\b', text, re.I)),
                           status='Source present; individual acceptance pending'))
    (OUT / 'surface-inventory.json').write_text(json.dumps(routes, indent=2), encoding='utf-8')
    assert len({(t['source_schema'], t['source_table']) for t in tables}) == len(tables)
    counts = {schema: sum(t['source_schema'] == schema for t in tables) for schema in ['public','hirava_core']}
    print(json.dumps({'application_models': counts, 'surfaces': len(routes), 'unmapped_models': 0}))


if __name__ == '__main__':
    build()
