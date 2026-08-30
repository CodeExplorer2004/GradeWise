from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, Float, Integer, String, bindparam, text
from sqlglot import exp, parse
from sqlglot.errors import ParseError

from app.core.config import get_settings
from app.core.database import ReadonlySessionLocal
from app.core.models import User, UserRole

settings = get_settings()

FORBIDDEN_NODE_TYPES = (
    exp.Alter,
    exp.Command,
    exp.Create,
    exp.Delete,
    exp.Drop,
    exp.Insert,
    exp.Merge,
    exp.Transaction,
    exp.Update,
    exp.With,
)
ALLOWED_FUNCTIONS = {
    "abs",
    "avg",
    "case",
    "cast",
    "coalesce",
    "count",
    "date_trunc",
    "dense_rank",
    "extract",
    "first_value",
    "if",
    "lag",
    "lead",
    "max",
    "min",
    "nullif",
    "percentile_cont",
    "rank",
    "round",
    "row_number",
    "stddev",
    "stddev_pop",
    "stddev_samp",
    "sum",
    "variance",
}
ALLOWED_TABLES = {"score_facts"}
ISO_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(slots=True)
class ValidationResult:
    allowed: bool
    normalized_sql: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)

    @property
    def display_sql(self) -> str | None:
        if not self.normalized_sql:
            return None
        return _to_sqlalchemy_named_params(self.normalized_sql, self.params)


class SQLSafetyGate:
    def validate(self, sql: str) -> ValidationResult:
        violations: list[str] = []
        if "--" in sql or "/*" in sql or "*/" in sql:
            violations.append("SQL_COMMENT_NOT_ALLOWED")
        if ";" in sql.rstrip().rstrip(";"):
            violations.append("STACKED_STATEMENT_NOT_ALLOWED")

        try:
            statements = parse(sql, read="postgres")
        except ParseError:
            return ValidationResult(False, violations=["SQL_PARSE_ERROR"])

        if len(statements) != 1:
            violations.append("EXACTLY_ONE_STATEMENT_REQUIRED")
        if not statements:
            return ValidationResult(False, violations=violations or ["EMPTY_SQL"])

        tree = statements[0]
        if not isinstance(tree, exp.Select):
            violations.append("ONLY_SELECT_ALLOWED")
        if any(tree.find_all(*FORBIDDEN_NODE_TYPES)):
            violations.append("DANGEROUS_STATEMENT")

        tables = {table.name.lower() for table in tree.find_all(exp.Table)}
        if not tables:
            violations.append("DATA_SOURCE_REQUIRED")
        unknown_tables = tables - ALLOWED_TABLES
        if unknown_tables:
            violations.append(f"TABLE_NOT_ALLOWED:{','.join(sorted(unknown_tables))}")

        for function in tree.find_all(exp.Func):
            # sqlglot models boolean operators as Func subclasses even though they
            # are SQL syntax, not callable functions subject to the function allowlist.
            if isinstance(function, (exp.And, exp.Or, exp.Not)):
                continue
            function_name = (
                function.name if isinstance(function, exp.Anonymous) else function.sql_name()
            ).lower()
            if function_name not in ALLOWED_FUNCTIONS:
                violations.append(f"FUNCTION_NOT_ALLOWED:{function_name}")

        if violations:
            return ValidationResult(False, violations=sorted(set(violations)))

        parameters: dict[str, Any] = {}

        def parameterize(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Literal):
                name = f"value_{len(parameters)}"
                value = node.to_py()
                if isinstance(value, str) and ISO_DATE_PATTERN.fullmatch(value):
                    value = date.fromisoformat(value)
                parameters[name] = value
                return exp.Placeholder(this=name)
            return node

        secured_tree = tree.transform(parameterize)
        if not secured_tree.args.get("limit"):
            secured_tree = secured_tree.limit(settings.query_max_rows)

        return ValidationResult(
            True,
            normalized_sql=secured_tree.sql(dialect="postgres"),
            params=parameters,
        )


def _scope_cte(user: User) -> tuple[str, dict[str, Any]]:
    if user.role == UserRole.STUDENT:
        if not user.student_id:
            raise PermissionError("学生账号未关联学生档案")
        return "student_id = :scope_student_id", {"scope_student_id": user.student_id}
    if user.role == UserRole.SUBJECT_TEACHER:
        if not user.teacher_id:
            raise PermissionError("教师账号未关联教师档案")
        return (
            "EXISTS (SELECT 1 FROM teaching_assignments ta "
            "WHERE ta.teacher_id = :scope_teacher_id "
            "AND ta.class_id = score_facts.class_id "
            "AND ta.subject_id = score_facts.subject_id "
            "AND ta.academic_year = score_facts.academic_year)",
            {"scope_teacher_id": user.teacher_id},
        )
    if user.role == UserRole.HEAD_TEACHER:
        if not user.teacher_id:
            raise PermissionError("班主任账号未关联教师档案")
        return (
            "EXISTS (SELECT 1 FROM classes c "
            "WHERE c.head_teacher_id = :scope_teacher_id "
            "AND c.id = score_facts.class_id "
            "AND c.academic_year = score_facts.academic_year)",
            {"scope_teacher_id": user.teacher_id},
        )
    if user.role == UserRole.ACADEMIC_ADMIN:
        return "school_id = :scope_school_id", {"scope_school_id": user.school_id}
    raise PermissionError("未知角色")


def _replace_source_with_authorized_cte(sql: str) -> str:
    tree = parse(sql, read="postgres")[0]
    for table in tree.find_all(exp.Table):
        if table.name.lower() == "score_facts":
            table.set("this", exp.to_identifier("authorized_score_facts"))
    return tree.sql(dialect="postgres")


def _to_sqlalchemy_named_params(sql: str, params: dict[str, Any]) -> str:
    for name in params:
        sql = sql.replace(f"%({name})s", f":{name}")
    return sql


def _bind_type(value: Any) -> Any:
    if isinstance(value, bool):
        return Boolean()
    if isinstance(value, int):
        return Integer()
    if isinstance(value, (float, Decimal)):
        return Float()
    if isinstance(value, date):
        return Date()
    return String()


async def execute_scoped_query(user: User, validation: ValidationResult) -> list[dict[str, Any]]:
    if not validation.allowed or not validation.normalized_sql:
        raise PermissionError("SQL 未通过安全校验")

    scope_where, scope_params = _scope_cte(user)
    scoped_query = _replace_source_with_authorized_cte(validation.normalized_sql)
    scoped_query = _to_sqlalchemy_named_params(scoped_query, validation.params)
    final_sql = (
        "WITH authorized_score_facts AS ("
        f"SELECT * FROM score_facts WHERE {scope_where}"
        f") {scoped_query}"
    )
    parameters = {**validation.params, **scope_params}

    async with ReadonlySessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET TRANSACTION READ ONLY"))
            await session.execute(
                text(f"SET LOCAL statement_timeout = {settings.query_timeout_ms}")
            )
            statement = text(final_sql).bindparams(
                *[
                    bindparam(name, type_=_bind_type(value))
                    for name, value in parameters.items()
                ]
            )
            result = await session.execute(statement, parameters)
            rows = result.mappings().fetchmany(settings.query_max_rows)
            return [dict(row) for row in rows]
