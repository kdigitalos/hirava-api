"""Own employee profile view with saved data and explicit empty states."""
from app.core.imported_identity import linked_employee
from app.data.imported import find, table
from app.modules.workforce.imported_assets import now, rows
from app.modules.workforce.imported_employee_profile import details, full_name
from app.modules.workforce.imported_self_service import PROFILE_FIELDS, profile_dto, profile_record, profile_payload


def initials(name):
    parts = name.split()
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else '')).upper() if parts else ''


def date_label(value):
    return value.strftime('%b %d, %Y') if value else ''


def employee_profile(db, user):
    employee = linked_employee(db, user, required=False)
    vm = {key: '' for key in [*PROFILE_FIELDS, *'employeeCode jobTitle joinedLabel department managerName workEmail workPhone initials dateOfBirth employmentType workLocation joinDate managerEmail directReports'.split()]}
    vm.update(employeeId=None, displayName=user.name or user.email, workEmail=user.email, personalEmail=user.email,
        initials=initials(user.name or user.email), pictureUrl=None,
        **{key: [] for key in ('benefits', 'requiredDocuments', 'myDocuments', 'requestHistory', 'assignedAssets', 'assetCareGuidelines', 'recentlyViewedPolicies', 'allPolicies')},
        requestStats={'total': 0, 'pending': 0, 'approved': 0, 'rejected': 0},
        assetStats={'totalAssets': 0, 'temporaryAssignments': 0, 'overdueReturns': 0})
    if employee:
        core = profile_payload(db, employee)['employee']
        stored = profile_dto(profile_record(db, employee['id']))
        vm.update({key: value for key, value in stored.items() if value is not None})
        vm.update(employeeId=employee['id'], employeeCode=employee['employeeCode'], displayName=full_name(employee),
            initials=initials(full_name(employee)), department=core['department'] or '', jobTitle=core['jobTitle'] or '',
            managerName=core['manager'] or '', workEmail=employee['email'] or user.email, workPhone=employee['phone'] or '',
            employmentType=employee['employmentType'] or '', workLocation=employee['workLocation'] or '', joinDate=date_label(employee['hireDate']))
        if employee['hireDate']:
            vm['joinedLabel'] = 'Joined: ' + date_label(employee['hireDate'])
        photo = details(employee).get('employeePhoto')
        if isinstance(photo, str) and photo:
            vm['pictureUrl'] = '/api/uploads/' + photo.lstrip('/')
        manager = find(db, 'Employee', employee['reportsToEmployeeId'], required=False) if employee['reportsToEmployeeId'] else None
        vm['managerEmail'] = manager.get('email') or '' if manager else ''
        direct = rows(db, 'Employee', table(db, 'Employee').c.reportsToEmployeeId == employee['id'], table(db, 'Employee').c.status != 'TERMINATED')
        vm['directReports'] = str(len(direct)) + ' team members'
        documents = rows(db, 'EmployeeDocument', table(db, 'EmployeeDocument').c.employeeId == employee['id'], order=table(db, 'EmployeeDocument').c.uploadedAt.desc())
        for row in documents:
            size = row['sizeBytes']
            vm['myDocuments'].append({'id': row['id'], 'title': row['title'], 'filename': row['originalFilename'],
                'type': row['documentType'] or row['category'], 'size': f'{size} B' if size < 1024 else f'{size / 1024:.1f} KB' if size < 1048576 else f'{size / 1048576:.1f} MB',
                'uploadDate': row['uploadedAt'].date().isoformat(), 'expiresDate': row['expiresAt'].isoformat()[:10] if row['expiresAt'] else '',
                'status': {'APPROVED': 'Approved', 'REJECTED': 'Rejected'}.get(row['status'], 'Pending'), 'rejectionReason': row['rejectionReason']})
        assignments = table(db, 'AssetAssignment')
        for assignment in rows(db, 'AssetAssignment', assignments.c.employeeId == employee['id'], assignments.c.returnedAt.is_(None), order=assignments.c.assignedAt.desc()):
            asset = find(db, 'Asset', assignment['assetId'])
            category = find(db, 'AssetCategory', asset['categoryId'], required=False) if asset['categoryId'] else None
            vm['assignedAssets'].append({'id': assignment['id'], 'assetId': asset['id'], 'assetCode': asset['assetTag'], 'name': asset['name'],
                'category': category['name'] if category else '', 'status': 'Allocated',
                'state': 'Damaged' if asset['condition'] == 'POOR' else 'Fair' if asset['condition'] in ('FAIR', 'USED') else 'Good',
                'assignedDate': date_label(assignment['assignedAt']), 'returnBy': 'Permanent'})
        vm['assetStats']['totalAssets'] = len(vm['assignedAssets'])
    policies = table(db, 'PrivacyPolicy')
    for row in rows(db, 'PrivacyPolicy', policies.c.status == 'ACTIVE', order=policies.c.updatedAt.desc()):
        kind = row['policyType'].lower()
        category = 'HR' if 'hr' in kind else 'Legal' if 'legal' in kind else 'Finance' if 'finance' in kind or 'payroll' in kind else 'IT'
        tags = [row['applicableTo']]
        if row['regionSpecific']:
            tags.append('Region-specific')
        if (now() - row['updatedAt']).days < 14:
            tags.append('New')
        vm['allPolicies'].append({**{key: row[key] for key in ('id', 'title', 'description', 'content')},
            'category': category, 'tags': tags, 'updatedDate': date_label(row['updatedAt']), 'acknowledged': False})
    # Viewing history and acknowledgements require evidence; never infer from order.
    return vm
