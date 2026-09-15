-- CreateSchema
CREATE SCHEMA IF NOT EXISTS "public";

-- CreateEnum
CREATE TYPE "UserRole" AS ENUM ('ADMIN', 'HR', 'MANAGER', 'EMPLOYEE');

-- CreateEnum
CREATE TYPE "EmployeeStatus" AS ENUM ('ACTIVE', 'ON_LEAVE', 'TERMINATED', 'PROBATION');

-- CreateEnum
CREATE TYPE "KnowledgeBaseArticleTag" AS ENUM ('HR', 'PAYROLL', 'IT', 'LEAVE', 'POLICY', 'FINANCE', 'GENERAL');

-- CreateEnum
CREATE TYPE "LeaveRequestStatus" AS ENUM ('PENDING', 'APPROVED', 'REJECTED', 'CANCELLED');

-- CreateEnum
CREATE TYPE "OnboardingCandidateStatus" AS ENUM ('INVITED', 'IN_PROGRESS', 'COMPLETED', 'WITHDRAWN');

-- CreateEnum
CREATE TYPE "ExitRequestStatus" AS ENUM ('PENDING', 'PENDING_HR', 'APPROVED', 'REJECTED', 'IN_PROGRESS', 'COMPLETED');

-- CreateEnum
CREATE TYPE "FnfSettlementStatus" AS ENUM ('DRAFT', 'UNDER_REVIEW', 'APPROVED', 'COMPLETED', 'OVERDUE');

-- CreateEnum
CREATE TYPE "AssetCondition" AS ENUM ('NEW', 'GOOD', 'FAIR', 'POOR', 'USED', 'REFURBISHED');

-- CreateEnum
CREATE TYPE "AssetStatus" AS ENUM ('AVAILABLE', 'ALLOCATED', 'IN_REPAIR', 'RETIRED', 'LOST', 'DISPOSED');

-- CreateEnum
CREATE TYPE "AssetReturnRequestStatus" AS ENUM ('PENDING_APPROVAL', 'APPROVED', 'REJECTED');

-- CreateEnum
CREATE TYPE "LostDamageIncidentType" AS ENUM ('LOST', 'DAMAGED');

-- CreateEnum
CREATE TYPE "LostDamagePriority" AS ENUM ('LOW', 'MEDIUM', 'HIGH');

-- CreateEnum
CREATE TYPE "LostDamageCaseStatus" AS ENUM ('UNDER_REVIEW', 'APPROVED', 'RESOLVED', 'REJECTED');

-- CreateEnum
CREATE TYPE "LostDamageWorkflowVisual" AS ENUM ('PURPLE_DOCUMENT', 'BLUE_CHECK', 'GREEN_DOLLAR');

-- CreateEnum
CREATE TYPE "OnboardingGroupStatus" AS ENUM ('DRAFT', 'ACTIVE', 'CONVERSION_PENDING', 'ARCHIVED');

-- CreateEnum
CREATE TYPE "OnboardingGroupProgress" AS ENUM ('GOOD', 'AVERAGE', 'BAD');

-- CreateEnum
CREATE TYPE "DocumentStatus" AS ENUM ('PENDING', 'APPROVED', 'REJECTED');

-- CreateEnum
CREATE TYPE "SelfServiceRequestType" AS ENUM ('PROFILE_UPDATE', 'LEAVE_ADJUSTMENT', 'ADDRESS_CHANGE', 'EMERGENCY_CONTACT', 'DOCUMENT_REQUEST', 'BANK_DETAILS');

-- CreateEnum
CREATE TYPE "SelfServiceRequestInitiator" AS ENUM ('SELF', 'MANAGER', 'HR');

-- CreateEnum
CREATE TYPE "SelfServiceRequestStatus" AS ENUM ('PENDING', 'APPROVED', 'REJECTED');

-- CreateEnum
CREATE TYPE "PrivacyPolicyStatus" AS ENUM ('ACTIVE', 'DRAFT', 'INACTIVE');

-- CreateEnum
CREATE TYPE "EmployeeTaskSource" AS ENUM ('LEAVE', 'LEARNING', 'ONBOARDING');

-- CreateEnum
CREATE TYPE "EmployeeTaskStatus" AS ENUM ('IN_PROGRESS', 'COMPLETED');

-- CreateEnum
CREATE TYPE "AdminScheduleItemType" AS ENUM ('MEETING', 'EVENT');

-- CreateEnum
CREATE TYPE "ProbationRecordStatus" AS ENUM ('ACTIVE_PROBATION', 'EXTENDED', 'CONFIRMED');

-- CreateEnum
CREATE TYPE "LifecycleEventKind" AS ENUM ('JOINED', 'ONBOARDING_COMPLETED', 'PROBATION_COMPLETED', 'CONFIRMED', 'OTHER');

-- CreateEnum
CREATE TYPE "AttendancePolicyCategory" AS ENUM ('LEAVE_TYPE', 'SHIFT', 'ENTITLEMENT');

-- CreateEnum
CREATE TYPE "AttendancePolicyStatus" AS ENUM ('ACTIVE', 'INACTIVE');

-- CreateEnum
CREATE TYPE "PerformanceGoalStatus" AS ENUM ('ACTIVE', 'COMPLETED', 'ARCHIVED');

-- CreateEnum
CREATE TYPE "ShiftType" AS ENUM ('MORNING', 'EVENING', 'NIGHT');

-- CreateEnum
CREATE TYPE "JobOpeningType" AS ENUM ('FULL_TIME', 'PART_TIME', 'INTERNSHIP', 'CONTRACT');

-- CreateEnum
CREATE TYPE "JobApplicationStatus" AS ENUM ('APPLIED', 'IN_REVIEW', 'INTERVIEW', 'REJECTED', 'OFFERED');

-- CreateEnum
CREATE TYPE "JobReferralStatus" AS ENUM ('PENDING', 'HIRED', 'REJECTED');

-- CreateEnum
CREATE TYPE "SubscriptionProduct" AS ENUM ('RMS', 'HRMS', 'RMS_HRMS');

-- CreateEnum
CREATE TYPE "SubscriptionPlan" AS ENUM ('QUARTERLY', 'HALF_YEARLY', 'ANNUAL');

-- CreateEnum
CREATE TYPE "SubscriptionRequestStatus" AS ENUM ('NEW', 'CONTACTED', 'IN_DISCUSSION', 'CONVERTED', 'REJECTED');

-- CreateEnum
CREATE TYPE "PartyType" AS ENUM ('INDIVIDUAL', 'ORGANIZATION');

-- CreateEnum
CREATE TYPE "PartyRoleType" AS ENUM ('VENDOR', 'CLIENT', 'SUPPLIER', 'CUSTOMER', 'PARTNER', 'CONTRACTOR');

-- CreateEnum
CREATE TYPE "PartyStatus" AS ENUM ('ACTIVE', 'INACTIVE', 'PROSPECT', 'ARCHIVED');

-- CreateEnum
CREATE TYPE "AddressType" AS ENUM ('BILLING', 'SHIPPING', 'OFFICE', 'HEADQUARTERS', 'MAILING');

-- CreateTable
CREATE TABLE "organization_role_settings" (
    "id" TEXT NOT NULL,
    "slug" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "isSystem" BOOLEAN NOT NULL DEFAULT false,
    "isDefault" BOOLEAN NOT NULL DEFAULT false,
    "permissions" JSONB NOT NULL,
    "sortOrder" INTEGER NOT NULL DEFAULT 0,
    "mapsToUserRole" "UserRole",
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "organization_role_settings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "auth0_sub" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "name" TEXT,
    "picture" TEXT,
    "role" "UserRole" NOT NULL DEFAULT 'EMPLOYEE',
    "last_login_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Department" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "code" TEXT,
    "description" TEXT,
    "department_head_employee_id" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Department_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "department_designations" (
    "id" TEXT NOT NULL,
    "department_id" TEXT NOT NULL,
    "title" VARCHAR(255) NOT NULL,
    "hierarchy_level" VARCHAR(128) NOT NULL,
    "description" TEXT NOT NULL DEFAULT '',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "department_designations_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "branches" (
    "id" TEXT NOT NULL,
    "name" VARCHAR(255) NOT NULL,
    "code" VARCHAR(64) NOT NULL,
    "street" VARCHAR(512) NOT NULL,
    "city" VARCHAR(255) NOT NULL,
    "state" VARCHAR(255) NOT NULL,
    "zip_code" VARCHAR(32) NOT NULL,
    "country" VARCHAR(255) NOT NULL,
    "description" TEXT NOT NULL,
    "contact_email" VARCHAR(255) NOT NULL,
    "contact_phone" VARCHAR(64) NOT NULL,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "branch_head_employee_id" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "branches_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "JobTitle" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "JobTitle_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Employee" (
    "id" TEXT NOT NULL,
    "user_id" TEXT,
    "employee_code" TEXT NOT NULL,
    "first_name" TEXT NOT NULL,
    "last_name" TEXT NOT NULL,
    "email" TEXT,
    "phone" TEXT,
    "branch_id" TEXT,
    "department_id" TEXT,
    "designation_id" TEXT,
    "job_title_id" TEXT,
    "employee_details" JSONB,
    "status" "EmployeeStatus" NOT NULL DEFAULT 'ACTIVE',
    "hire_date" DATE,
    "termination_date" DATE,
    "employment_type" VARCHAR(64),
    "work_location" VARCHAR(255),
    "reports_to_employee_id" TEXT,
    "org_sort_order" INTEGER NOT NULL DEFAULT 0,
    "payroll_json" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Employee_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_lifecycle_events" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "kind" "LifecycleEventKind" NOT NULL DEFAULT 'OTHER',
    "title" VARCHAR(200) NOT NULL,
    "occurred_on" DATE NOT NULL,
    "bullets" JSONB NOT NULL DEFAULT '[]',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "employee_lifecycle_events_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_tasks" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "title" VARCHAR(512) NOT NULL,
    "description" TEXT NOT NULL,
    "source" "EmployeeTaskSource" NOT NULL,
    "due_date" DATE NOT NULL,
    "status" "EmployeeTaskStatus" NOT NULL DEFAULT 'IN_PROGRESS',
    "detail_kind" VARCHAR(32) NOT NULL DEFAULT 'generic',
    "next_steps_json" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "employee_tasks_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "probation_records" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "reporting_manager" TEXT NOT NULL,
    "joining_date" DATE NOT NULL,
    "probation_start" DATE NOT NULL,
    "probation_end" DATE NOT NULL,
    "extensions" INTEGER NOT NULL DEFAULT 0,
    "status" "ProbationRecordStatus" NOT NULL DEFAULT 'ACTIVE_PROBATION',
    "confirmed_at" TIMESTAMP(3),
    "reviews_json" JSONB,
    "extension_events_json" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "probation_records_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "probation_policy_settings" (
    "id" TEXT NOT NULL,
    "default_duration_months" INTEGER NOT NULL,
    "max_extensions" INTEGER NOT NULL,
    "auto_confirmation_enabled" BOOLEAN NOT NULL DEFAULT false,
    "full_time_duration_months" INTEGER NOT NULL,
    "contract_duration_months" INTEGER NOT NULL,
    "reminder_30_enabled" BOOLEAN NOT NULL DEFAULT true,
    "reminder_15_enabled" BOOLEAN NOT NULL DEFAULT true,
    "reminder_7_enabled" BOOLEAN NOT NULL DEFAULT true,
    "department_durations" JSONB,
    "approval_workflow" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "probation_policy_settings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "OnboardingGroup" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "role_label" TEXT,
    "location" TEXT,
    "manager" TEXT,
    "department" TEXT,
    "auto_convert" BOOLEAN NOT NULL DEFAULT true,
    "status" "OnboardingGroupStatus" NOT NULL DEFAULT 'DRAFT',
    "group_code" TEXT,
    "progress" "OnboardingGroupProgress",
    "progress_percent" INTEGER,
    "current_task" INTEGER,
    "window_start" DATE,
    "window_end" DATE,
    "probation_policy" TEXT,
    "template_source" TEXT,
    "additional_recipients" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "OnboardingGroup_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "OnboardingTemplate" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "group_id" TEXT,
    "category" TEXT,
    "template_type" TEXT,
    "complexity" TEXT,
    "department" TEXT,
    "stages_json" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "OnboardingTemplate_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "OnboardingCandidate" (
    "id" TEXT NOT NULL,
    "group_id" TEXT NOT NULL,
    "template_id" TEXT,
    "employee_id" TEXT,
    "email" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "role_label" TEXT,
    "details" JSONB,
    "status" "OnboardingCandidateStatus" NOT NULL DEFAULT 'INVITED',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "OnboardingCandidate_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LeaveType" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "days_per_year" INTEGER,
    "color_hex" VARCHAR(7),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "LeaveType_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public_holidays" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "holiday_date" DATE NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "public_holidays_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LeaveBalance" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "leave_type_id" TEXT NOT NULL,
    "year" INTEGER NOT NULL,
    "balance_days" DOUBLE PRECISION NOT NULL DEFAULT 0,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "LeaveBalance_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "LeaveRequest" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "leave_type_id" TEXT NOT NULL,
    "start_date" DATE NOT NULL,
    "end_date" DATE NOT NULL,
    "status" "LeaveRequestStatus" NOT NULL DEFAULT 'PENDING',
    "reason" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "LeaveRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AssetCategory" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "id_prefix" VARCHAR(32) NOT NULL,
    "description" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AssetCategory_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "asset_vendors" (
    "id" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "party_id" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "asset_vendors_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "asset_photos" (
    "id" TEXT NOT NULL,
    "asset_id" TEXT NOT NULL,
    "original_filename" VARCHAR(255) NOT NULL,
    "storage_path" TEXT NOT NULL,
    "mime_type" TEXT NOT NULL,
    "size_bytes" INTEGER NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "asset_photos_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Asset" (
    "id" TEXT NOT NULL,
    "asset_tag" VARCHAR(64) NOT NULL,
    "name" TEXT NOT NULL,
    "model" VARCHAR(255),
    "serial_number" VARCHAR(128),
    "category_id" TEXT,
    "condition" "AssetCondition" NOT NULL DEFAULT 'NEW',
    "status" "AssetStatus" NOT NULL DEFAULT 'AVAILABLE',
    "vendor_id" TEXT,
    "purchase_order" VARCHAR(128),
    "invoice_number" VARCHAR(128),
    "purchase_date" DATE,
    "purchase_value" DECIMAL(14,2),
    "useful_life_months" INTEGER,
    "warranty_end_date" DATE,
    "location" VARCHAR(512) NOT NULL,
    "department_id" TEXT,
    "notes" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "Asset_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AssetAssignment" (
    "id" TEXT NOT NULL,
    "asset_id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "assigned_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "returned_at" TIMESTAMP(3),
    "notes" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AssetAssignment_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "asset_return_requests" (
    "id" TEXT NOT NULL,
    "asset_assignment_id" TEXT NOT NULL,
    "requested_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "expected_return_date" DATE NOT NULL,
    "reason" TEXT NOT NULL,
    "status" "AssetReturnRequestStatus" NOT NULL DEFAULT 'PENDING_APPROVAL',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "asset_return_requests_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "lost_damage_incidents" (
    "id" TEXT NOT NULL,
    "incident_number" VARCHAR(32) NOT NULL,
    "asset_id" TEXT NOT NULL,
    "reporter_employee_id" TEXT NOT NULL,
    "incident_type" "LostDamageIncidentType" NOT NULL,
    "incident_date" DATE NOT NULL,
    "location" VARCHAR(512) NOT NULL,
    "description" TEXT NOT NULL,
    "attachments_json" JSONB,
    "estimated_cost" DECIMAL(14,2),
    "priority" "LostDamagePriority" NOT NULL DEFAULT 'MEDIUM',
    "status" "LostDamageCaseStatus" NOT NULL DEFAULT 'UNDER_REVIEW',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "lost_damage_incidents_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "lost_damage_policy_guidelines" (
    "id" TEXT NOT NULL,
    "sort_order" INTEGER NOT NULL,
    "title" VARCHAR(200) NOT NULL,
    "body" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "lost_damage_policy_guidelines_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "lost_damage_workflow_steps" (
    "id" TEXT NOT NULL,
    "sort_order" INTEGER NOT NULL,
    "title" VARCHAR(200) NOT NULL,
    "description" TEXT NOT NULL,
    "visual" "LostDamageWorkflowVisual" NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "lost_damage_workflow_steps_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "attendance_policies" (
    "id" TEXT NOT NULL,
    "category" "AttendancePolicyCategory" NOT NULL,
    "name" VARCHAR(200) NOT NULL,
    "status" "AttendancePolicyStatus" NOT NULL DEFAULT 'ACTIVE',
    "sort_order" INTEGER NOT NULL DEFAULT 0,
    "config" JSONB NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "attendance_policies_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "AttendanceRecord" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "work_date" DATE NOT NULL,
    "check_in" TIMESTAMP(3),
    "check_out" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "AttendanceRecord_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "ExitRequest" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "status" "ExitRequestStatus" NOT NULL DEFAULT 'PENDING',
    "exit_type" TEXT,
    "resignation_date" DATE,
    "last_working_date" DATE,
    "reason" TEXT,
    "additional_notes" TEXT,
    "notice_waived" BOOLEAN NOT NULL DEFAULT false,
    "employee_code_entered" TEXT,
    "full_name_entered" TEXT,
    "department_entered" TEXT,
    "manager_entered" TEXT,
    "contact_email" TEXT,
    "policy_accepted" BOOLEAN NOT NULL DEFAULT false,
    "is_draft" BOOLEAN NOT NULL DEFAULT false,
    "attachments_json" JSONB,
    "clearance_json" JSONB,
    "applied_template_id" TEXT,
    "applied_template_json" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ExitRequest_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "fnf_settlements" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "exit_request_id" TEXT,
    "exit_date" DATE NOT NULL,
    "department_label" VARCHAR(255) NOT NULL,
    "net_amount_paise" INTEGER NOT NULL,
    "company_payout_paise" INTEGER,
    "employee_recovery_paise" INTEGER,
    "status" "FnfSettlementStatus" NOT NULL DEFAULT 'DRAFT',
    "notes" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "fnf_settlements_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "exit_offboarding_templates" (
    "id" TEXT NOT NULL,
    "name" VARCHAR(255) NOT NULL,
    "role_label" VARCHAR(255),
    "department_label" VARCHAR(255),
    "location_label" VARCHAR(255),
    "description" TEXT,
    "stages_json" JSONB NOT NULL,
    "stage_count" INTEGER NOT NULL DEFAULT 0,
    "task_count" INTEGER NOT NULL DEFAULT 0,
    "total_days" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "exit_offboarding_templates_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_documents" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "category" TEXT NOT NULL DEFAULT 'general',
    "title" TEXT NOT NULL,
    "original_filename" TEXT NOT NULL,
    "storage_path" TEXT NOT NULL,
    "mime_type" TEXT NOT NULL,
    "size_bytes" INTEGER NOT NULL,
    "document_type" TEXT,
    "expires_at" DATE,
    "status" "DocumentStatus" NOT NULL DEFAULT 'PENDING',
    "rejection_reason" TEXT,
    "uploaded_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "employee_documents_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "organization_company_profile" (
    "id" TEXT NOT NULL,
    "logo_storage_path" TEXT,
    "company_name" VARCHAR(255) NOT NULL DEFAULT '',
    "industry" VARCHAR(255) NOT NULL DEFAULT '',
    "email" VARCHAR(255) NOT NULL DEFAULT '',
    "phone" VARCHAR(64) NOT NULL DEFAULT '',
    "website" VARCHAR(512) NOT NULL DEFAULT '',
    "tax_id" VARCHAR(128) NOT NULL DEFAULT '',
    "description" TEXT NOT NULL DEFAULT '',
    "street_address" VARCHAR(512) NOT NULL DEFAULT '',
    "city" VARCHAR(255) NOT NULL DEFAULT '',
    "state" VARCHAR(255),
    "zip_code" VARCHAR(32),
    "country" VARCHAR(255),
    "default_currency" VARCHAR(128) NOT NULL DEFAULT '',
    "timezone" VARCHAR(128),
    "work_start_time" VARCHAR(8),
    "work_end_time" VARCHAR(8),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "organization_company_profile_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "privacy_policies" (
    "id" TEXT NOT NULL,
    "title" TEXT NOT NULL,
    "policy_type" TEXT NOT NULL,
    "applicable_to" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "region_specific" BOOLEAN NOT NULL DEFAULT false,
    "status" "PrivacyPolicyStatus" NOT NULL DEFAULT 'DRAFT',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "privacy_policies_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "support_tickets" (
    "id" TEXT NOT NULL,
    "ticket_number" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "status" TEXT NOT NULL DEFAULT 'Open',
    "priority" TEXT NOT NULL DEFAULT 'Medium',
    "category" TEXT NOT NULL,
    "department" TEXT,
    "title" TEXT NOT NULL,
    "description" TEXT NOT NULL,
    "due_at" TIMESTAMP(3),
    "resolved_at" TIMESTAMP(3),
    "closed_at" TIMESTAMP(3),
    "assigned_to_employee_id" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "support_tickets_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "knowledge_base_articles" (
    "id" TEXT NOT NULL,
    "title" VARCHAR(512) NOT NULL,
    "excerpt" TEXT NOT NULL,
    "content" TEXT NOT NULL,
    "tag" "KnowledgeBaseArticleTag" NOT NULL DEFAULT 'GENERAL',
    "category" VARCHAR(128) NOT NULL DEFAULT '',
    "tags" JSONB NOT NULL DEFAULT '[]',
    "views" INTEGER NOT NULL DEFAULT 0,
    "helpful" INTEGER NOT NULL DEFAULT 0,
    "read_time_minutes" INTEGER NOT NULL DEFAULT 3,
    "is_published" BOOLEAN NOT NULL DEFAULT true,
    "published_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "knowledge_base_articles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "knowledge_base_faqs" (
    "id" TEXT NOT NULL,
    "question" VARCHAR(512) NOT NULL,
    "answer" TEXT NOT NULL,
    "is_published" BOOLEAN NOT NULL DEFAULT true,
    "sort_order" INTEGER NOT NULL DEFAULT 0,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "knowledge_base_faqs_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "performance_feedback" (
    "id" TEXT NOT NULL,
    "from_employee_id" TEXT NOT NULL,
    "to_employee_id" TEXT NOT NULL,
    "rating" INTEGER NOT NULL,
    "comment" TEXT NOT NULL,
    "sentiment" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "performance_feedback_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_shifts" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "shift_date" DATE NOT NULL,
    "shift_type" "ShiftType" NOT NULL DEFAULT 'MORNING',
    "start_label" VARCHAR(32) NOT NULL,
    "end_label" VARCHAR(32) NOT NULL,
    "location" VARCHAR(128) NOT NULL DEFAULT '',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "employee_shifts_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "performance_goals" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "title" VARCHAR(255) NOT NULL,
    "description" TEXT NOT NULL DEFAULT '',
    "progress" INTEGER NOT NULL DEFAULT 0,
    "weight" INTEGER NOT NULL DEFAULT 0,
    "target" VARCHAR(128),
    "due_date" DATE,
    "status" "PerformanceGoalStatus" NOT NULL DEFAULT 'ACTIVE',
    "tags" JSONB NOT NULL DEFAULT '[]',
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "performance_goals_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "performance_appraisals" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "cycle_label" VARCHAR(64) NOT NULL,
    "period_label" VARCHAR(64),
    "status" VARCHAR(64) NOT NULL DEFAULT 'Not Started',
    "self_assessment_status" VARCHAR(64) NOT NULL DEFAULT 'Pending',
    "self_score" DOUBLE PRECISION,
    "manager_review_status" VARCHAR(64) NOT NULL DEFAULT 'Pending',
    "manager_review_due" DATE,
    "submitted_at" TIMESTAMP(3),
    "key_achievements" TEXT,
    "challenges_overcome" TEXT,
    "areas_for_growth" TEXT,
    "support_need" TEXT,
    "goal_ratings_json" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "performance_appraisals_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_self_service_requests" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "request_type" "SelfServiceRequestType" NOT NULL,
    "initiated_by" "SelfServiceRequestInitiator" NOT NULL,
    "status" "SelfServiceRequestStatus" NOT NULL DEFAULT 'PENDING',
    "submitted_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "notes" TEXT,
    "reference_code" TEXT NOT NULL,
    "payload_json" JSONB,
    "reviewed_at" TIMESTAMP(3),
    "reviewed_by_id" TEXT,
    "review_note" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "employee_self_service_requests_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "employee_profiles" (
    "id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "date_of_birth" DATE,
    "nationality" TEXT,
    "marital_status" TEXT,
    "display_name" TEXT,
    "gender" TEXT,
    "country" TEXT,
    "state" TEXT,
    "preferred_language" TEXT,
    "time_zone" VARCHAR(512),
    "personal_email" TEXT,
    "personal_phone" TEXT,
    "home_address" TEXT,
    "permanent_address" TEXT,
    "emergency_name" TEXT,
    "emergency_phone" TEXT,
    "emergency_email" TEXT,
    "emergency_relationship" TEXT,
    "social_security_number" TEXT,
    "drivers_license" TEXT,
    "passport_number" TEXT,
    "past_company_name" TEXT,
    "past_job_title" TEXT,
    "past_employment_type" TEXT,
    "past_start_date" TEXT,
    "past_end_date" TEXT,
    "past_location" TEXT,
    "past_responsibilities" TEXT,
    "degree" TEXT,
    "field_of_study" TEXT,
    "institution" TEXT,
    "edu_start_date" TEXT,
    "edu_end_date" TEXT,
    "grade" TEXT,
    "mode_of_study" TEXT,
    "edu_location" TEXT,
    "work_schedule" TEXT,
    "last_promotion_date" TEXT,
    "salary_band" TEXT,
    "pay_frequency" TEXT,
    "bank_name" TEXT,
    "bank_account_number" TEXT,
    "bank_routing_number" TEXT,
    "benefits" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "employee_profiles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "announcements" (
    "id" TEXT NOT NULL,
    "title" VARCHAR(255) NOT NULL,
    "body" TEXT NOT NULL,
    "tag" VARCHAR(64) NOT NULL DEFAULT 'General',
    "department" VARCHAR(128),
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "published_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "announcements_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "admin_schedule_items" (
    "id" TEXT NOT NULL,
    "item_type" "AdminScheduleItemType" NOT NULL,
    "title" VARCHAR(200) NOT NULL,
    "location" VARCHAR(200) NOT NULL,
    "start_at" TIMESTAMP(3) NOT NULL,
    "end_at" TIMESTAMP(3) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "admin_schedule_items_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "job_openings" (
    "id" TEXT NOT NULL,
    "title" VARCHAR(255) NOT NULL,
    "type" "JobOpeningType" NOT NULL DEFAULT 'FULL_TIME',
    "salary_min" INTEGER NOT NULL DEFAULT 0,
    "salary_max" INTEGER NOT NULL DEFAULT 0,
    "company" VARCHAR(255) NOT NULL DEFAULT '',
    "location" VARCHAR(255) NOT NULL DEFAULT '',
    "department" VARCHAR(128) NOT NULL DEFAULT '',
    "logo" VARCHAR(32) NOT NULL DEFAULT 'default',
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "job_openings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "job_applications" (
    "id" TEXT NOT NULL,
    "job_opening_id" TEXT NOT NULL,
    "employee_id" TEXT NOT NULL,
    "status" "JobApplicationStatus" NOT NULL DEFAULT 'APPLIED',
    "cover_letter" TEXT,
    "applied_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "job_applications_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "job_referrals" (
    "id" TEXT NOT NULL,
    "referred_by_employee_id" TEXT NOT NULL,
    "job_opening_id" TEXT,
    "candidate_name" VARCHAR(255) NOT NULL,
    "candidate_email" VARCHAR(255) NOT NULL,
    "role" VARCHAR(255) NOT NULL,
    "status" "JobReferralStatus" NOT NULL DEFAULT 'PENDING',
    "referred_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "job_referrals_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_job_openings" (
    "id" SERIAL NOT NULL,
    "job_title" VARCHAR(255),
    "company_name" VARCHAR(255),
    "recruiter" TEXT,
    "status" VARCHAR(50) DEFAULT '',
    "hiring_due_date" TIMESTAMP(6),
    "job_id" VARCHAR(100),
    "job_type" VARCHAR(100),
    "work_mode" VARCHAR(100),
    "job_description" TEXT,
    "job_link" TEXT,
    "budget" INTEGER,
    "no_of_openings" INTEGER,
    "extra_fields" JSONB,
    "location" TEXT,
    "candidate_ids" VARCHAR(100)[],
    "hiring_flow" TEXT,
    "required_skills" VARCHAR[],
    "created_by" VARCHAR(100),
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_job_openings_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_section_value" (
    "id" SERIAL NOT NULL,
    "value" VARCHAR(255),
    "object" JSONB,
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_section_value_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_hiring_flow" (
    "id" SERIAL NOT NULL,
    "value" VARCHAR,
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_hiring_flow_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_template" (
    "id" SERIAL NOT NULL,
    "subject" TEXT NOT NULL,
    "body" TEXT NOT NULL,
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_template_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_candidate_form_details" (
    "id" SERIAL NOT NULL,
    "job_opening_id" INTEGER NOT NULL,
    "first_name" VARCHAR(100) DEFAULT '',
    "last_name" VARCHAR(100) DEFAULT '',
    "gender" VARCHAR(50) DEFAULT '',
    "date_of_birth" TIMESTAMP(6),
    "mobile" VARCHAR(50) DEFAULT '',
    "email" VARCHAR(255) DEFAULT '',
    "notice_period" VARCHAR(100) DEFAULT '',
    "current_job_title" VARCHAR(255) DEFAULT '',
    "current_ctc" VARCHAR(100) DEFAULT '',
    "expected_ctc" VARCHAR(100) DEFAULT '',
    "current_company" VARCHAR(255) DEFAULT '',
    "current_location" VARCHAR(255) DEFAULT '',
    "linkedin_id" VARCHAR(255) DEFAULT '',
    "referred_by" VARCHAR(255) DEFAULT '',
    "available_time" VARCHAR(100) DEFAULT '',
    "location_preference" VARCHAR(255) DEFAULT '',
    "upload_resume" VARCHAR(500) DEFAULT '',
    "extra_field" JSONB DEFAULT '{}',
    "questions" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_candidate_form_details_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_question" (
    "id" SERIAL NOT NULL,
    "candidate_id" INTEGER NOT NULL,
    "question" TEXT,
    "question_type" VARCHAR(100) DEFAULT '',
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_question_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_candidate" (
    "id" SERIAL NOT NULL,
    "job_opening_id" INTEGER NOT NULL,
    "object" JSONB DEFAULT '{}',
    "updated_by" VARCHAR(255) DEFAULT '',
    "status" VARCHAR(50) DEFAULT '',
    "contacted" VARCHAR(50) DEFAULT 'Not contacted',
    "questions" JSONB DEFAULT '{}',
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_candidate_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_interview" (
    "id" SERIAL NOT NULL,
    "company_name" VARCHAR(255) DEFAULT '',
    "job_id" INTEGER NOT NULL,
    "candidate_id" INTEGER,
    "interview_date" TIMESTAMP(6) NOT NULL,
    "interview_time" VARCHAR(50) DEFAULT '',
    "duration" VARCHAR(100) DEFAULT '',
    "panel_members" VARCHAR(100) DEFAULT '',
    "candidate_name" VARCHAR(255) DEFAULT '',
    "meeting_platform" VARCHAR(100) DEFAULT '',
    "interview_type" VARCHAR(100) DEFAULT '',
    "email" TEXT DEFAULT '',
    "hiring_flow" JSONB DEFAULT '{}',
    "s2" TEXT,
    "s3" TEXT,
    "s4" TEXT,
    "f1" TEXT,
    "f2" TEXT,
    "f3" TEXT,
    "f4" TEXT,
    "f5" TEXT,
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_interview_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_interview_schedule" (
    "id" SERIAL NOT NULL,
    "interview_id" INTEGER NOT NULL,
    "job_id" INTEGER NOT NULL,
    "candidate_id" INTEGER,
    "interview_date" TIMESTAMP(6) NOT NULL,
    "interview_time" VARCHAR(50) DEFAULT '',
    "duration" VARCHAR(100) DEFAULT '',
    "panel_members" VARCHAR(100) DEFAULT '',
    "meeting_platform" VARCHAR(100) DEFAULT '',
    "interview_type" VARCHAR(100) DEFAULT '',
    "email" TEXT DEFAULT '',
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_interview_schedule_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "rms_feedback" (
    "id" SERIAL NOT NULL,
    "interviewer_name" VARCHAR(255),
    "date" TIMESTAMP(6),
    "time" VARCHAR(50),
    "interview_mode" VARCHAR(100),
    "overall_rating" INTEGER,
    "final_recommendation" TEXT,
    "description" TEXT,
    "interview_id" INTEGER,
    "candidate_id" INTEGER,
    "level" INTEGER,
    "job_id" INTEGER,
    "created_at" TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(6) DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "rms_feedback_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "client_subscription_requests" (
    "id" TEXT NOT NULL,
    "company_name" VARCHAR(255) NOT NULL,
    "legal_entity_name" VARCHAR(255),
    "industry" VARCHAR(160),
    "company_registration_number" VARCHAR(120),
    "gst_number" VARCHAR(60),
    "pan_number" VARCHAR(30),
    "cin_number" VARCHAR(60),
    "company_website" VARCHAR(255),
    "year_of_establishment" INTEGER,
    "number_of_employees" INTEGER,
    "number_of_branches" INTEGER,
    "headquarters_location" VARCHAR(255),
    "primary_contact_name" VARCHAR(160) NOT NULL,
    "primary_contact_designation" VARCHAR(160),
    "primary_contact_email" VARCHAR(255) NOT NULL,
    "primary_contact_mobile" VARCHAR(40) NOT NULL,
    "alternate_contact_name" VARCHAR(160),
    "alternate_contact_designation" VARCHAR(160),
    "alternate_contact_email" VARCHAR(255),
    "alternate_contact_mobile" VARCHAR(40),
    "registered_address" TEXT,
    "registered_city" VARCHAR(120),
    "registered_state" VARCHAR(120),
    "registered_country" VARCHAR(120),
    "registered_pin_code" VARCHAR(20),
    "corporate_same_as_registered" BOOLEAN NOT NULL DEFAULT false,
    "corporate_address" TEXT,
    "corporate_city" VARCHAR(120),
    "corporate_state" VARCHAR(120),
    "corporate_country" VARCHAR(120),
    "corporate_pin_code" VARCHAR(20),
    "product_required" "SubscriptionProduct" NOT NULL,
    "subscription_plan" "SubscriptionPlan" NOT NULL,
    "rms_user_count" INTEGER,
    "hrms_user_count" INTEGER,
    "expected_go_live_date" DATE,
    "status" "SubscriptionRequestStatus" NOT NULL DEFAULT 'NEW',
    "internal_notes" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "client_subscription_requests_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "parties" (
    "id" TEXT NOT NULL,
    "auth0_user_id" TEXT,
    "code" VARCHAR(64),
    "name" VARCHAR(255) NOT NULL,
    "legal_name" VARCHAR(255),
    "party_type" "PartyType" NOT NULL DEFAULT 'ORGANIZATION',
    "status" "PartyStatus" NOT NULL DEFAULT 'ACTIVE',
    "tax_id" VARCHAR(100),
    "gstin" VARCHAR(60),
    "pan" VARCHAR(30),
    "email" VARCHAR(255),
    "phone" VARCHAR(50),
    "website" VARCHAR(255),
    "currency" VARCHAR(10) NOT NULL DEFAULT 'USD',
    "notes" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "parties_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "party_roles" (
    "id" TEXT NOT NULL,
    "party_id" TEXT NOT NULL,
    "role_type" "PartyRoleType" NOT NULL,
    "status" "PartyStatus" NOT NULL DEFAULT 'ACTIVE',
    "notes" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "party_roles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "roles" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "roles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "party_user_roles" (
    "id" TEXT NOT NULL,
    "party_id" TEXT NOT NULL,
    "role_id" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "party_user_roles_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "modules" (
    "id" TEXT NOT NULL,
    "code" TEXT NOT NULL,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "modules_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "role_modules" (
    "id" TEXT NOT NULL,
    "role_id" TEXT NOT NULL,
    "module_id" TEXT NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "role_modules_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "party_contact_persons" (
    "id" TEXT NOT NULL,
    "party_id" TEXT NOT NULL,
    "name" VARCHAR(160) NOT NULL,
    "designation" VARCHAR(160),
    "email" VARCHAR(255),
    "phone" VARCHAR(50),
    "is_primary" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "party_contact_persons_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "party_addresses" (
    "id" TEXT NOT NULL,
    "party_id" TEXT NOT NULL,
    "address_type" "AddressType" NOT NULL DEFAULT 'OFFICE',
    "address_line1" TEXT NOT NULL,
    "address_line2" TEXT,
    "city" VARCHAR(120) NOT NULL,
    "state" VARCHAR(120) NOT NULL,
    "postal_code" VARCHAR(30) NOT NULL,
    "country" VARCHAR(120) NOT NULL DEFAULT 'USA',
    "is_primary" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "party_addresses_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "party_bank_details" (
    "id" TEXT NOT NULL,
    "party_id" TEXT NOT NULL,
    "bank_name" VARCHAR(160) NOT NULL,
    "account_number" VARCHAR(100) NOT NULL,
    "account_name" VARCHAR(160) NOT NULL,
    "ifsc_swift" VARCHAR(50),
    "branch_name" VARCHAR(160),
    "is_primary" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "party_bank_details_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "organization_role_settings_slug_key" ON "organization_role_settings"("slug");

-- CreateIndex
CREATE UNIQUE INDEX "User_auth0_sub_key" ON "User"("auth0_sub");

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE UNIQUE INDEX "Department_code_key" ON "Department"("code");

-- CreateIndex
CREATE INDEX "Department_department_head_employee_id_idx" ON "Department"("department_head_employee_id");

-- CreateIndex
CREATE INDEX "department_designations_department_id_idx" ON "department_designations"("department_id");

-- CreateIndex
CREATE UNIQUE INDEX "branches_code_key" ON "branches"("code");

-- CreateIndex
CREATE INDEX "branches_city_idx" ON "branches"("city");

-- CreateIndex
CREATE INDEX "branches_is_active_idx" ON "branches"("is_active");

-- CreateIndex
CREATE UNIQUE INDEX "Employee_user_id_key" ON "Employee"("user_id");

-- CreateIndex
CREATE UNIQUE INDEX "Employee_employee_code_key" ON "Employee"("employee_code");

-- CreateIndex
CREATE INDEX "Employee_branch_id_idx" ON "Employee"("branch_id");

-- CreateIndex
CREATE INDEX "Employee_designation_id_idx" ON "Employee"("designation_id");

-- CreateIndex
CREATE INDEX "Employee_reports_to_employee_id_org_sort_order_idx" ON "Employee"("reports_to_employee_id", "org_sort_order");

-- CreateIndex
CREATE INDEX "employee_lifecycle_events_employee_id_idx" ON "employee_lifecycle_events"("employee_id");

-- CreateIndex
CREATE INDEX "employee_lifecycle_events_employee_id_occurred_on_idx" ON "employee_lifecycle_events"("employee_id", "occurred_on");

-- CreateIndex
CREATE INDEX "employee_tasks_employee_id_idx" ON "employee_tasks"("employee_id");

-- CreateIndex
CREATE INDEX "employee_tasks_employee_id_due_date_idx" ON "employee_tasks"("employee_id", "due_date");

-- CreateIndex
CREATE INDEX "probation_records_employee_id_idx" ON "probation_records"("employee_id");

-- CreateIndex
CREATE INDEX "probation_records_probation_end_idx" ON "probation_records"("probation_end");

-- CreateIndex
CREATE INDEX "probation_records_status_idx" ON "probation_records"("status");

-- CreateIndex
CREATE UNIQUE INDEX "OnboardingGroup_group_code_key" ON "OnboardingGroup"("group_code");

-- CreateIndex
CREATE INDEX "OnboardingTemplate_category_idx" ON "OnboardingTemplate"("category");

-- CreateIndex
CREATE INDEX "OnboardingTemplate_template_type_idx" ON "OnboardingTemplate"("template_type");

-- CreateIndex
CREATE INDEX "OnboardingTemplate_complexity_idx" ON "OnboardingTemplate"("complexity");

-- CreateIndex
CREATE INDEX "OnboardingTemplate_department_idx" ON "OnboardingTemplate"("department");

-- CreateIndex
CREATE UNIQUE INDEX "public_holidays_holiday_date_key" ON "public_holidays"("holiday_date");

-- CreateIndex
CREATE UNIQUE INDEX "LeaveBalance_employee_id_leave_type_id_year_key" ON "LeaveBalance"("employee_id", "leave_type_id", "year");

-- CreateIndex
CREATE UNIQUE INDEX "AssetCategory_id_prefix_key" ON "AssetCategory"("id_prefix");

-- CreateIndex
CREATE INDEX "AssetCategory_name_idx" ON "AssetCategory"("name");

-- CreateIndex
CREATE INDEX "asset_photos_asset_id_idx" ON "asset_photos"("asset_id");

-- CreateIndex
CREATE UNIQUE INDEX "Asset_asset_tag_key" ON "Asset"("asset_tag");

-- CreateIndex
CREATE UNIQUE INDEX "Asset_serial_number_key" ON "Asset"("serial_number");

-- CreateIndex
CREATE INDEX "Asset_category_id_idx" ON "Asset"("category_id");

-- CreateIndex
CREATE INDEX "Asset_status_idx" ON "Asset"("status");

-- CreateIndex
CREATE INDEX "Asset_vendor_id_idx" ON "Asset"("vendor_id");

-- CreateIndex
CREATE INDEX "Asset_department_id_idx" ON "Asset"("department_id");

-- CreateIndex
CREATE INDEX "AssetAssignment_asset_id_idx" ON "AssetAssignment"("asset_id");

-- CreateIndex
CREATE INDEX "AssetAssignment_employee_id_idx" ON "AssetAssignment"("employee_id");

-- CreateIndex
CREATE INDEX "AssetAssignment_returned_at_idx" ON "AssetAssignment"("returned_at");

-- CreateIndex
CREATE INDEX "asset_return_requests_asset_assignment_id_idx" ON "asset_return_requests"("asset_assignment_id");

-- CreateIndex
CREATE INDEX "asset_return_requests_status_idx" ON "asset_return_requests"("status");

-- CreateIndex
CREATE UNIQUE INDEX "lost_damage_incidents_incident_number_key" ON "lost_damage_incidents"("incident_number");

-- CreateIndex
CREATE INDEX "lost_damage_incidents_asset_id_idx" ON "lost_damage_incidents"("asset_id");

-- CreateIndex
CREATE INDEX "lost_damage_incidents_status_idx" ON "lost_damage_incidents"("status");

-- CreateIndex
CREATE INDEX "lost_damage_incidents_reporter_employee_id_idx" ON "lost_damage_incidents"("reporter_employee_id");

-- CreateIndex
CREATE INDEX "lost_damage_incidents_created_at_idx" ON "lost_damage_incidents"("created_at");

-- CreateIndex
CREATE INDEX "lost_damage_policy_guidelines_sort_order_idx" ON "lost_damage_policy_guidelines"("sort_order");

-- CreateIndex
CREATE INDEX "lost_damage_workflow_steps_sort_order_idx" ON "lost_damage_workflow_steps"("sort_order");

-- CreateIndex
CREATE INDEX "attendance_policies_category_sort_order_idx" ON "attendance_policies"("category", "sort_order");

-- CreateIndex
CREATE UNIQUE INDEX "AttendanceRecord_employee_id_work_date_key" ON "AttendanceRecord"("employee_id", "work_date");

-- CreateIndex
CREATE INDEX "fnf_settlements_employee_id_idx" ON "fnf_settlements"("employee_id");

-- CreateIndex
CREATE INDEX "fnf_settlements_status_idx" ON "fnf_settlements"("status");

-- CreateIndex
CREATE INDEX "fnf_settlements_exit_date_idx" ON "fnf_settlements"("exit_date");

-- CreateIndex
CREATE INDEX "exit_offboarding_templates_name_idx" ON "exit_offboarding_templates"("name");

-- CreateIndex
CREATE INDEX "employee_documents_employee_id_idx" ON "employee_documents"("employee_id");

-- CreateIndex
CREATE INDEX "employee_documents_employee_id_category_idx" ON "employee_documents"("employee_id", "category");

-- CreateIndex
CREATE UNIQUE INDEX "support_tickets_ticket_number_key" ON "support_tickets"("ticket_number");

-- CreateIndex
CREATE INDEX "support_tickets_employee_id_idx" ON "support_tickets"("employee_id");

-- CreateIndex
CREATE INDEX "support_tickets_assigned_to_employee_id_idx" ON "support_tickets"("assigned_to_employee_id");

-- CreateIndex
CREATE INDEX "support_tickets_status_idx" ON "support_tickets"("status");

-- CreateIndex
CREATE INDEX "knowledge_base_articles_is_published_idx" ON "knowledge_base_articles"("is_published");

-- CreateIndex
CREATE INDEX "knowledge_base_articles_tag_idx" ON "knowledge_base_articles"("tag");

-- CreateIndex
CREATE INDEX "knowledge_base_articles_views_idx" ON "knowledge_base_articles"("views");

-- CreateIndex
CREATE INDEX "knowledge_base_faqs_is_published_idx" ON "knowledge_base_faqs"("is_published");

-- CreateIndex
CREATE INDEX "knowledge_base_faqs_sort_order_idx" ON "knowledge_base_faqs"("sort_order");

-- CreateIndex
CREATE INDEX "performance_feedback_from_employee_id_idx" ON "performance_feedback"("from_employee_id");

-- CreateIndex
CREATE INDEX "performance_feedback_to_employee_id_idx" ON "performance_feedback"("to_employee_id");

-- CreateIndex
CREATE INDEX "employee_shifts_employee_id_shift_date_idx" ON "employee_shifts"("employee_id", "shift_date");

-- CreateIndex
CREATE UNIQUE INDEX "employee_shifts_employee_id_shift_date_key" ON "employee_shifts"("employee_id", "shift_date");

-- CreateIndex
CREATE INDEX "performance_goals_employee_id_idx" ON "performance_goals"("employee_id");

-- CreateIndex
CREATE INDEX "performance_goals_employee_id_status_idx" ON "performance_goals"("employee_id", "status");

-- CreateIndex
CREATE INDEX "performance_appraisals_employee_id_idx" ON "performance_appraisals"("employee_id");

-- CreateIndex
CREATE UNIQUE INDEX "employee_self_service_requests_reference_code_key" ON "employee_self_service_requests"("reference_code");

-- CreateIndex
CREATE INDEX "employee_self_service_requests_employee_id_idx" ON "employee_self_service_requests"("employee_id");

-- CreateIndex
CREATE INDEX "employee_self_service_requests_status_idx" ON "employee_self_service_requests"("status");

-- CreateIndex
CREATE INDEX "employee_self_service_requests_submitted_at_idx" ON "employee_self_service_requests"("submitted_at");

-- CreateIndex
CREATE INDEX "employee_self_service_requests_employee_id_request_type_sta_idx" ON "employee_self_service_requests"("employee_id", "request_type", "status");

-- CreateIndex
CREATE UNIQUE INDEX "employee_profiles_employee_id_key" ON "employee_profiles"("employee_id");

-- CreateIndex
CREATE INDEX "announcements_is_active_published_at_idx" ON "announcements"("is_active", "published_at");

-- CreateIndex
CREATE INDEX "admin_schedule_items_item_type_start_at_idx" ON "admin_schedule_items"("item_type", "start_at");

-- CreateIndex
CREATE INDEX "admin_schedule_items_start_at_idx" ON "admin_schedule_items"("start_at");

-- CreateIndex
CREATE INDEX "job_openings_is_active_idx" ON "job_openings"("is_active");

-- CreateIndex
CREATE INDEX "job_openings_department_idx" ON "job_openings"("department");

-- CreateIndex
CREATE INDEX "job_applications_employee_id_idx" ON "job_applications"("employee_id");

-- CreateIndex
CREATE INDEX "job_applications_job_opening_id_idx" ON "job_applications"("job_opening_id");

-- CreateIndex
CREATE INDEX "job_applications_status_idx" ON "job_applications"("status");

-- CreateIndex
CREATE UNIQUE INDEX "job_applications_job_opening_id_employee_id_key" ON "job_applications"("job_opening_id", "employee_id");

-- CreateIndex
CREATE INDEX "job_referrals_referred_by_employee_id_idx" ON "job_referrals"("referred_by_employee_id");

-- CreateIndex
CREATE INDEX "job_referrals_status_idx" ON "job_referrals"("status");

-- CreateIndex
CREATE INDEX "client_subscription_requests_status_idx" ON "client_subscription_requests"("status");

-- CreateIndex
CREATE INDEX "client_subscription_requests_created_at_idx" ON "client_subscription_requests"("created_at");

-- CreateIndex
CREATE INDEX "client_subscription_requests_primary_contact_email_idx" ON "client_subscription_requests"("primary_contact_email");

-- CreateIndex
CREATE UNIQUE INDEX "parties_auth0_user_id_key" ON "parties"("auth0_user_id");

-- CreateIndex
CREATE UNIQUE INDEX "parties_code_key" ON "parties"("code");

-- CreateIndex
CREATE INDEX "parties_status_idx" ON "parties"("status");

-- CreateIndex
CREATE INDEX "parties_party_type_idx" ON "parties"("party_type");

-- CreateIndex
CREATE INDEX "parties_name_idx" ON "parties"("name");

-- CreateIndex
CREATE UNIQUE INDEX "party_roles_party_id_role_type_key" ON "party_roles"("party_id", "role_type");

-- CreateIndex
CREATE UNIQUE INDEX "roles_code_key" ON "roles"("code");

-- CreateIndex
CREATE INDEX "party_user_roles_party_id_idx" ON "party_user_roles"("party_id");

-- CreateIndex
CREATE INDEX "party_user_roles_role_id_idx" ON "party_user_roles"("role_id");

-- CreateIndex
CREATE UNIQUE INDEX "party_user_roles_party_id_role_id_key" ON "party_user_roles"("party_id", "role_id");

-- CreateIndex
CREATE UNIQUE INDEX "modules_code_key" ON "modules"("code");

-- CreateIndex
CREATE INDEX "role_modules_role_id_idx" ON "role_modules"("role_id");

-- CreateIndex
CREATE INDEX "role_modules_module_id_idx" ON "role_modules"("module_id");

-- CreateIndex
CREATE UNIQUE INDEX "role_modules_role_id_module_id_key" ON "role_modules"("role_id", "module_id");

-- AddForeignKey
ALTER TABLE "Department" ADD CONSTRAINT "Department_department_head_employee_id_fkey" FOREIGN KEY ("department_head_employee_id") REFERENCES "Employee"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "department_designations" ADD CONSTRAINT "department_designations_department_id_fkey" FOREIGN KEY ("department_id") REFERENCES "Department"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "branches" ADD CONSTRAINT "branches_branch_head_employee_id_fkey" FOREIGN KEY ("branch_head_employee_id") REFERENCES "Employee"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Employee" ADD CONSTRAINT "Employee_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Employee" ADD CONSTRAINT "Employee_branch_id_fkey" FOREIGN KEY ("branch_id") REFERENCES "branches"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Employee" ADD CONSTRAINT "Employee_department_id_fkey" FOREIGN KEY ("department_id") REFERENCES "Department"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Employee" ADD CONSTRAINT "Employee_designation_id_fkey" FOREIGN KEY ("designation_id") REFERENCES "department_designations"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Employee" ADD CONSTRAINT "Employee_job_title_id_fkey" FOREIGN KEY ("job_title_id") REFERENCES "JobTitle"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Employee" ADD CONSTRAINT "Employee_reports_to_employee_id_fkey" FOREIGN KEY ("reports_to_employee_id") REFERENCES "Employee"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_lifecycle_events" ADD CONSTRAINT "employee_lifecycle_events_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_tasks" ADD CONSTRAINT "employee_tasks_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "probation_records" ADD CONSTRAINT "probation_records_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "OnboardingTemplate" ADD CONSTRAINT "OnboardingTemplate_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "OnboardingGroup"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "OnboardingCandidate" ADD CONSTRAINT "OnboardingCandidate_group_id_fkey" FOREIGN KEY ("group_id") REFERENCES "OnboardingGroup"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "OnboardingCandidate" ADD CONSTRAINT "OnboardingCandidate_template_id_fkey" FOREIGN KEY ("template_id") REFERENCES "OnboardingTemplate"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "OnboardingCandidate" ADD CONSTRAINT "OnboardingCandidate_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LeaveBalance" ADD CONSTRAINT "LeaveBalance_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LeaveBalance" ADD CONSTRAINT "LeaveBalance_leave_type_id_fkey" FOREIGN KEY ("leave_type_id") REFERENCES "LeaveType"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LeaveRequest" ADD CONSTRAINT "LeaveRequest_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "LeaveRequest" ADD CONSTRAINT "LeaveRequest_leave_type_id_fkey" FOREIGN KEY ("leave_type_id") REFERENCES "LeaveType"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "asset_vendors" ADD CONSTRAINT "asset_vendors_party_id_fkey" FOREIGN KEY ("party_id") REFERENCES "parties"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "asset_photos" ADD CONSTRAINT "asset_photos_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Asset" ADD CONSTRAINT "Asset_category_id_fkey" FOREIGN KEY ("category_id") REFERENCES "AssetCategory"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Asset" ADD CONSTRAINT "Asset_vendor_id_fkey" FOREIGN KEY ("vendor_id") REFERENCES "asset_vendors"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "Asset" ADD CONSTRAINT "Asset_department_id_fkey" FOREIGN KEY ("department_id") REFERENCES "Department"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssetAssignment" ADD CONSTRAINT "AssetAssignment_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "Asset"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AssetAssignment" ADD CONSTRAINT "AssetAssignment_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "asset_return_requests" ADD CONSTRAINT "asset_return_requests_asset_assignment_id_fkey" FOREIGN KEY ("asset_assignment_id") REFERENCES "AssetAssignment"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "lost_damage_incidents" ADD CONSTRAINT "lost_damage_incidents_asset_id_fkey" FOREIGN KEY ("asset_id") REFERENCES "Asset"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "lost_damage_incidents" ADD CONSTRAINT "lost_damage_incidents_reporter_employee_id_fkey" FOREIGN KEY ("reporter_employee_id") REFERENCES "Employee"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "AttendanceRecord" ADD CONSTRAINT "AttendanceRecord_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ExitRequest" ADD CONSTRAINT "ExitRequest_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "ExitRequest" ADD CONSTRAINT "ExitRequest_applied_template_id_fkey" FOREIGN KEY ("applied_template_id") REFERENCES "exit_offboarding_templates"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "fnf_settlements" ADD CONSTRAINT "fnf_settlements_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "fnf_settlements" ADD CONSTRAINT "fnf_settlements_exit_request_id_fkey" FOREIGN KEY ("exit_request_id") REFERENCES "ExitRequest"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_documents" ADD CONSTRAINT "employee_documents_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "support_tickets" ADD CONSTRAINT "support_tickets_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "support_tickets" ADD CONSTRAINT "support_tickets_assigned_to_employee_id_fkey" FOREIGN KEY ("assigned_to_employee_id") REFERENCES "Employee"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "performance_feedback" ADD CONSTRAINT "performance_feedback_from_employee_id_fkey" FOREIGN KEY ("from_employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "performance_feedback" ADD CONSTRAINT "performance_feedback_to_employee_id_fkey" FOREIGN KEY ("to_employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_shifts" ADD CONSTRAINT "employee_shifts_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "performance_goals" ADD CONSTRAINT "performance_goals_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "performance_appraisals" ADD CONSTRAINT "performance_appraisals_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_self_service_requests" ADD CONSTRAINT "employee_self_service_requests_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_self_service_requests" ADD CONSTRAINT "employee_self_service_requests_reviewed_by_id_fkey" FOREIGN KEY ("reviewed_by_id") REFERENCES "User"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "employee_profiles" ADD CONSTRAINT "employee_profiles_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "job_applications" ADD CONSTRAINT "job_applications_job_opening_id_fkey" FOREIGN KEY ("job_opening_id") REFERENCES "job_openings"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "job_applications" ADD CONSTRAINT "job_applications_employee_id_fkey" FOREIGN KEY ("employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "job_referrals" ADD CONSTRAINT "job_referrals_referred_by_employee_id_fkey" FOREIGN KEY ("referred_by_employee_id") REFERENCES "Employee"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "job_referrals" ADD CONSTRAINT "job_referrals_job_opening_id_fkey" FOREIGN KEY ("job_opening_id") REFERENCES "job_openings"("id") ON DELETE SET NULL ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "party_roles" ADD CONSTRAINT "party_roles_party_id_fkey" FOREIGN KEY ("party_id") REFERENCES "parties"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "party_user_roles" ADD CONSTRAINT "party_user_roles_party_id_fkey" FOREIGN KEY ("party_id") REFERENCES "parties"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "party_user_roles" ADD CONSTRAINT "party_user_roles_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "roles"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "role_modules" ADD CONSTRAINT "role_modules_role_id_fkey" FOREIGN KEY ("role_id") REFERENCES "roles"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "role_modules" ADD CONSTRAINT "role_modules_module_id_fkey" FOREIGN KEY ("module_id") REFERENCES "modules"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "party_contact_persons" ADD CONSTRAINT "party_contact_persons_party_id_fkey" FOREIGN KEY ("party_id") REFERENCES "parties"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "party_addresses" ADD CONSTRAINT "party_addresses_party_id_fkey" FOREIGN KEY ("party_id") REFERENCES "parties"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "party_bank_details" ADD CONSTRAINT "party_bank_details_party_id_fkey" FOREIGN KEY ("party_id") REFERENCES "parties"("id") ON DELETE CASCADE ON UPDATE CASCADE;
