import type { AnalysisScope } from '@/types'

function storageKey(userId: number) {
  return `gradewise:analysis-scope:${userId}`
}

export function loadAnalysisScope(userId?: number): AnalysisScope {
  if (!userId) return {}
  try {
    return JSON.parse(localStorage.getItem(storageKey(userId)) || '{}') as AnalysisScope
  } catch {
    return {}
  }
}

export function saveAnalysisScope(userId: number | undefined, scope: AnalysisScope) {
  if (userId) localStorage.setItem(storageKey(userId), JSON.stringify(scope))
}

export function analysisScopeLabel(scope: AnalysisScope) {
  return [
    scope.academic_year && `${scope.academic_year}学年`,
    scope.grade_level,
    scope.cohort_year && `${scope.cohort_year}届`,
    scope.term,
    scope.exam_type,
    scope.class_name,
    scope.subject_name,
    scope.exam_name,
  ].filter(Boolean).join(' · ')
}
