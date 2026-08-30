import random
from collections.abc import Sequence
from datetime import date

from faker import Faker
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.models import (
    ClassMembership,
    Exam,
    ExamScore,
    GradeSubjectConfig,
    RiskSnapshot,
    School,
    SchoolClass,
    Student,
    Subject,
    Teacher,
    TeachingAssignment,
    User,
    UserRole,
)
from app.core.scoring import quantize_score
from app.core.security import hash_password

settings = get_settings()

DEMO_ACADEMIC_YEAR = "2026-2027"
DEMO_GRADE_LEVEL = "初三"
DEMO_COHORT_YEAR = 2024
DEMO_CLASS_COUNT = 6
DEMO_STUDENTS_PER_CLASS = 42
DEMO_SUBJECT_SCHEMES = (
    ("CHN", "语文", 150.0, 90.0),
    ("MATH", "数学", 150.0, 90.0),
    ("ENG", "英语", 150.0, 90.0),
    ("PHY", "物理", 100.0, 60.0),
    ("CHEM", "化学", 100.0, 60.0),
    ("POL", "政治", 100.0, 60.0),
    ("HIST", "历史", 100.0, 60.0),
)
DEMO_SUBJECT_TEACHER_COUNTS = {
    "CHN": 3,
    "MATH": 3,
    "ENG": 3,
    "PHY": 2,
    "CHEM": 2,
    "POL": 2,
    "HIST": 2,
}
ADDITIONAL_SUBJECT_SCHEMES = (
    ("GEO", "地理", 100.0, 60.0),
    ("BIO", "生物", 100.0, 60.0),
)
ALL_SUBJECT_SCHEMES = DEMO_SUBJECT_SCHEMES + ADDITIONAL_SUBJECT_SCHEMES
GRADE_SUBJECT_CODES = {
    "初一": ("CHN", "MATH", "ENG", "POL", "HIST", "GEO", "BIO"),
    "初二": ("CHN", "MATH", "ENG", "POL", "PHY", "HIST", "GEO", "BIO"),
    "初三": ("CHN", "MATH", "ENG", "POL", "HIST", "PHY", "CHEM"),
}
GRADE_TAGS = {"初一": "g1", "初二": "g2"}
GRADE_COHORT_YEARS = {"初一": 2026, "初二": 2025, "初三": DEMO_COHORT_YEAR}
ADDITIONAL_GRADE_EXAMS = (
    ("上学期期中考试", "第一学期", "期中", date(2026, 11, 15)),
    ("上学期期末考试", "第一学期", "期末", date(2027, 1, 20)),
    ("下学期月考", "第二学期", "月考", date(2027, 3, 15)),
    ("下学期期中考试", "第二学期", "期中", date(2027, 4, 25)),
    ("下学期期末考试", "第二学期", "期末", date(2027, 6, 25)),
)
DEMO_EXAMS = (
    ("初三上学期期中考试", "第一学期", "期中", date(2026, 11, 15)),
    ("初三上学期期末考试", "第一学期", "期末", date(2027, 1, 20)),
    ("初三下学期一模", "第二学期", "一模", date(2027, 3, 20)),
    ("初三下学期二模", "第二学期", "二模", date(2027, 4, 25)),
    ("初三中考模拟", "第二学期", "模拟考", date(2027, 5, 25)),
)


def _teacher_for_class(teachers: Sequence[Teacher], class_index: int) -> Teacher:
    """Distribute a subject's teachers evenly across all demo classes."""
    teacher_index = min(
        class_index * len(teachers) // DEMO_CLASS_COUNT,
        len(teachers) - 1,
    )
    return teachers[teacher_index]


def build_demo_score_values(
    students_by_class: list[list[Student]],
    exam_count: int,
    subject_max_scores: Sequence[float],
    random_seed: int = 20260826,
) -> dict[tuple[int, int, int], float]:
    """Generate correlated score rates, then scale each subject to its configured maximum."""
    if any(max_score <= 0 for max_score in subject_max_scores):
        raise ValueError("科目满分必须大于 0")

    rng = random.Random(random_seed)
    exam_difficulty = (-1.0, 0.2, -0.6, 0.0, 0.8)
    class_effects = (3.2, 2.0, 0.8, -0.4, -1.4, -2.4)
    values: dict[tuple[int, int, int], float] = {}

    for class_index, class_students in enumerate(students_by_class):
        for student_position, student in enumerate(class_students):
            ability_roll = rng.random()
            if ability_roll < 0.12:
                ability = rng.gauss(63, 3.5)
            elif ability_roll < 0.28:
                ability = rng.gauss(87, 3)
            else:
                ability = rng.gauss(78, 5)
            growth = rng.gauss(0.55, 0.35)

            for subject_index, max_score in enumerate(subject_max_scores):
                subject_offset = rng.gauss(0, 3.0)
                profile_roll = rng.random()
                persistent_penalty = -10.0 if profile_roll < 0.05 else 0.0
                decline_step = -5.0 if 0.05 <= profile_roll < 0.085 else 0.0
                final_shock = -15.0 if 0.085 <= profile_roll < 0.11 else 0.0

                for exam_index in range(exam_count):
                    difficulty = exam_difficulty[min(exam_index, len(exam_difficulty) - 1)]
                    score = (
                        ability
                        + class_effects[min(class_index, len(class_effects) - 1)]
                        + subject_offset
                        + difficulty
                        + exam_index * (growth + decline_step)
                        + persistent_penalty
                        + rng.gauss(0, 2.4)
                    )
                    if final_shock and exam_index == exam_count - 1:
                        score += final_shock
                    score_rate = max(35.0, min(100.0, score))
                    values[(student.id, exam_index, subject_index)] = quantize_score(
                        score_rate * max_score / 100
                    )
                controlled_scores: tuple[float, ...] | None = None
                if class_index == 0 and student_position == 0 and subject_index == 1:
                    controlled_scores = (70.0, 64.0, 58.0, 52.0, 46.0)
                elif class_index == 2 and student_position == 0 and subject_index == 4:
                    controlled_scores = (74.0, 68.0, 61.0, 55.0, 47.0)
                elif class_index == 4 and student_position == 0 and subject_index == 5:
                    controlled_scores = (76.0, 68.0, 61.0, 54.0, 48.0)
                if controlled_scores:
                    for exam_index, controlled_score in enumerate(controlled_scores[:exam_count]):
                        values[(student.id, exam_index, subject_index)] = quantize_score(
                            controlled_score * max_score / 100
                        )
    return values


async def seed_demo_data(session: AsyncSession) -> None:
    existing_school = await session.scalar(select(School).order_by(School.id))
    if existing_school:
        await ensure_demo_grade_data(session, existing_school)
        return

    fake = Faker("zh_CN")
    Faker.seed(20260826)

    school = School(name="格致实验学校")
    session.add(school)
    await session.flush()

    subjects = [
        Subject(
            school_id=school.id,
            code=code,
            name=name,
            max_score=max_score,
            pass_score=pass_score,
        )
        for code, name, max_score, pass_score in DEMO_SUBJECT_SCHEMES
    ]
    session.add_all(subjects)
    await session.flush()

    teachers: list[Teacher] = []
    teachers_by_subject: dict[str, list[Teacher]] = {}
    teacher_number = 1
    for code, _, _, _ in DEMO_SUBJECT_SCHEMES:
        subject_teachers = [
            Teacher(
                school_id=school.id,
                teacher_no=f"T{teacher_number + offset:03d}",
                display_name=fake.name(),
            )
            for offset in range(DEMO_SUBJECT_TEACHER_COUNTS[code])
        ]
        teachers_by_subject[code] = subject_teachers
        teachers.extend(subject_teachers)
        teacher_number += len(subject_teachers)
    session.add_all(teachers)
    await session.flush()

    core_subject_codes = ("CHN", "MATH", "ENG")
    classes = [
        SchoolClass(
            school_id=school.id,
            name=f"初三{class_index + 1}班",
            grade_level=DEMO_GRADE_LEVEL,
            academic_year=DEMO_ACADEMIC_YEAR,
            cohort_year=DEMO_COHORT_YEAR,
            head_teacher_id=_teacher_for_class(
                teachers_by_subject[core_subject_codes[class_index % len(core_subject_codes)]],
                class_index,
            ).id,
        )
        for class_index in range(DEMO_CLASS_COUNT)
    ]
    session.add_all(classes)
    await session.flush()

    exams = [
        Exam(
            school_id=school.id,
            name=name,
            academic_year=DEMO_ACADEMIC_YEAR,
            grade_level=DEMO_GRADE_LEVEL,
            term=term,
            exam_type=exam_type,
            exam_date=exam_date,
        )
        for name, term, exam_type, exam_date in DEMO_EXAMS
    ]
    session.add_all(exams)
    await session.flush()

    for class_index, school_class in enumerate(classes):
        for subject in subjects:
            teacher = _teacher_for_class(teachers_by_subject[subject.code], class_index)
            session.add(
                TeachingAssignment(
                    teacher_id=teacher.id,
                    class_id=school_class.id,
                    subject_id=subject.id,
                    academic_year=DEMO_ACADEMIC_YEAR,
                )
            )

    students: list[Student] = []
    students_by_class: list[list[Student]] = []
    memberships: list[ClassMembership] = []
    for class_index, school_class in enumerate(classes, start=1):
        class_students: list[Student] = []
        for seat in range(1, DEMO_STUDENTS_PER_CLASS + 1):
            student = Student(
                school_id=school.id,
                student_no=f"2026{class_index:02d}{seat:02d}",
                display_name=fake.name(),
            )
            session.add(student)
            await session.flush()
            students.append(student)
            class_students.append(student)
            memberships.append(
                ClassMembership(
                    student_id=student.id,
                    class_id=school_class.id,
                    academic_year=DEMO_ACADEMIC_YEAR,
                )
            )
        students_by_class.append(class_students)
    session.add_all(memberships)

    score_values = build_demo_score_values(
        students_by_class,
        len(exams),
        [subject.max_score for subject in subjects],
    )
    for class_index, school_class in enumerate(classes):
        for student in students_by_class[class_index]:
            for exam_index, exam in enumerate(exams):
                for subject_index, subject in enumerate(subjects):
                    session.add(
                        ExamScore(
                            student_id=student.id,
                            class_id=school_class.id,
                            exam_id=exam.id,
                            subject_id=subject.id,
                            score=score_values[(student.id, exam_index, subject_index)],
                        )
                    )

    shared_hash = hash_password(settings.demo_password)
    head_teacher_ids = [school_class.head_teacher_id for school_class in classes]
    session.add_all(
        [
            User(
                school_id=school.id,
                username="student01",
                password_hash=shared_hash,
                role=UserRole.STUDENT,
                student_id=students[0].id,
            ),
            *[
                User(
                    school_id=school.id,
                    username=f"teacher{index:02d}",
                    password_hash=shared_hash,
                    role=UserRole.SUBJECT_TEACHER,
                    teacher_id=teacher.id,
                )
                for index, teacher in enumerate(teachers, start=1)
            ],
            *[
                User(
                    school_id=school.id,
                    username=f"headteacher{index:02d}",
                    password_hash=shared_hash,
                    role=UserRole.HEAD_TEACHER,
                    teacher_id=teacher_id,
                )
                for index, teacher_id in enumerate(head_teacher_ids, start=1)
            ],
            User(
                school_id=school.id,
                username="academic01",
                password_hash=shared_hash,
                role=UserRole.ACADEMIC_ADMIN,
            ),
        ]
    )
    await session.commit()
    await ensure_demo_grade_data(session, school)


async def _ensure_subjects(
    session: AsyncSession, school: School
) -> dict[str, Subject]:
    subjects = list(
        (
            await session.scalars(
                select(Subject).where(Subject.school_id == school.id).order_by(Subject.id)
            )
        ).all()
    )
    subjects_by_code = {subject.code: subject for subject in subjects}
    for code, name, max_score, pass_score in ALL_SUBJECT_SCHEMES:
        subject = subjects_by_code.get(code)
        if subject is None:
            subject = Subject(
                school_id=school.id,
                code=code,
                name=name,
                max_score=max_score,
                pass_score=pass_score,
            )
            session.add(subject)
            subjects_by_code[code] = subject
        else:
            subject.name = name
            subject.max_score = max_score
            subject.pass_score = pass_score
    await session.flush()
    return subjects_by_code


async def _ensure_curriculum(
    session: AsyncSession,
    school: School,
    subjects_by_code: dict[str, Subject],
) -> None:
    existing = list(
        (
            await session.scalars(
                select(GradeSubjectConfig).where(
                    GradeSubjectConfig.school_id == school.id,
                    GradeSubjectConfig.academic_year == DEMO_ACADEMIC_YEAR,
                )
            )
        ).all()
    )
    config_map = {(item.grade_level, item.subject_id): item for item in existing}
    schemes_by_code = {
        code: (max_score, pass_score)
        for code, _, max_score, pass_score in ALL_SUBJECT_SCHEMES
    }
    for grade_level, subject_codes in GRADE_SUBJECT_CODES.items():
        for sort_order, code in enumerate(subject_codes, start=1):
            subject = subjects_by_code[code]
            max_score, pass_score = schemes_by_code[code]
            config = config_map.get((grade_level, subject.id))
            if config is None:
                session.add(
                    GradeSubjectConfig(
                        school_id=school.id,
                        academic_year=DEMO_ACADEMIC_YEAR,
                        grade_level=grade_level,
                        subject_id=subject.id,
                        max_score=max_score,
                        pass_score=pass_score,
                        included_in_total=True,
                        sort_order=sort_order,
                    )
                )
            else:
                config.max_score = max_score
                config.pass_score = pass_score
                config.included_in_total = True
                config.sort_order = sort_order


def _grade_head_teacher(
    teachers_by_subject: dict[str, list[Teacher]], class_index: int
) -> Teacher:
    core_subject_codes = ("CHN", "MATH", "ENG")
    code = core_subject_codes[class_index % len(core_subject_codes)]
    return _teacher_for_class(teachers_by_subject[code], class_index)


async def _ensure_grade_teachers(
    session: AsyncSession,
    school: School,
    grade_level: str,
    subject_codes: Sequence[str],
) -> tuple[list[Teacher], dict[str, list[Teacher]]]:
    grade_tag = GRADE_TAGS[grade_level].upper()
    existing = list(
        (
            await session.scalars(
                select(Teacher).where(
                    Teacher.school_id == school.id,
                    Teacher.teacher_no.like(f"{grade_tag}-%"),
                )
            )
        ).all()
    )
    teacher_map = {teacher.teacher_no: teacher for teacher in existing}
    fake = Faker("zh_CN")
    fake.seed_instance(20260826 + (1 if grade_level == "初一" else 2))
    teachers: list[Teacher] = []
    teachers_by_subject: dict[str, list[Teacher]] = {}
    for code in subject_codes:
        teacher_count = DEMO_SUBJECT_TEACHER_COUNTS.get(code, 2)
        subject_teachers: list[Teacher] = []
        for index in range(1, teacher_count + 1):
            teacher_no = f"{grade_tag}-{code}-{index:02d}"
            teacher = teacher_map.get(teacher_no)
            if teacher is None:
                teacher = Teacher(
                    school_id=school.id,
                    teacher_no=teacher_no,
                    display_name=fake.name(),
                )
                session.add(teacher)
                teacher_map[teacher_no] = teacher
            subject_teachers.append(teacher)
            teachers.append(teacher)
        teachers_by_subject[code] = subject_teachers
    await session.flush()
    return teachers, teachers_by_subject


async def _ensure_grade_classes(
    session: AsyncSession,
    school: School,
    grade_level: str,
    teachers_by_subject: dict[str, list[Teacher]],
) -> list[SchoolClass]:
    existing = list(
        (
            await session.scalars(
                select(SchoolClass).where(
                    SchoolClass.school_id == school.id,
                    SchoolClass.academic_year == DEMO_ACADEMIC_YEAR,
                    SchoolClass.grade_level == grade_level,
                )
            )
        ).all()
    )
    class_map = {school_class.name: school_class for school_class in existing}
    classes: list[SchoolClass] = []
    for class_index in range(DEMO_CLASS_COUNT):
        name = f"{grade_level}{class_index + 1}班"
        school_class = class_map.get(name)
        head_teacher = _grade_head_teacher(teachers_by_subject, class_index)
        if school_class is None:
            school_class = SchoolClass(
                school_id=school.id,
                name=name,
                grade_level=grade_level,
                academic_year=DEMO_ACADEMIC_YEAR,
                cohort_year=GRADE_COHORT_YEARS[grade_level],
                head_teacher_id=head_teacher.id,
            )
            session.add(school_class)
        else:
            school_class.cohort_year = GRADE_COHORT_YEARS[grade_level]
            school_class.head_teacher_id = head_teacher.id
        classes.append(school_class)
    await session.flush()
    return classes


async def _ensure_grade_exams(
    session: AsyncSession, school: School, grade_level: str
) -> list[Exam]:
    existing = list(
        (
            await session.scalars(
                select(Exam).where(
                    Exam.school_id == school.id,
                    Exam.academic_year == DEMO_ACADEMIC_YEAR,
                    Exam.grade_level == grade_level,
                )
            )
        ).all()
    )
    exam_map = {exam.name: exam for exam in existing}
    exams: list[Exam] = []
    for suffix, term, exam_type, exam_date in ADDITIONAL_GRADE_EXAMS:
        name = f"{grade_level}{suffix}"
        exam = exam_map.get(name)
        if exam is None:
            exam = Exam(
                school_id=school.id,
                name=name,
                academic_year=DEMO_ACADEMIC_YEAR,
                grade_level=grade_level,
                term=term,
                exam_type=exam_type,
                exam_date=exam_date,
            )
            session.add(exam)
        exams.append(exam)
    await session.flush()
    return exams


async def _ensure_grade_assignments(
    session: AsyncSession,
    classes: Sequence[SchoolClass],
    subjects_by_code: dict[str, Subject],
    subject_codes: Sequence[str],
    teachers_by_subject: dict[str, list[Teacher]],
) -> None:
    class_ids = [school_class.id for school_class in classes]
    existing = list(
        (
            await session.scalars(
                select(TeachingAssignment).where(TeachingAssignment.class_id.in_(class_ids))
            )
        ).all()
    )
    assignment_keys = {
        (item.teacher_id, item.class_id, item.subject_id, item.academic_year)
        for item in existing
    }
    for class_index, school_class in enumerate(classes):
        for code in subject_codes:
            teacher = _teacher_for_class(teachers_by_subject[code], class_index)
            subject = subjects_by_code[code]
            key = (teacher.id, school_class.id, subject.id, DEMO_ACADEMIC_YEAR)
            if key not in assignment_keys:
                session.add(
                    TeachingAssignment(
                        teacher_id=teacher.id,
                        class_id=school_class.id,
                        subject_id=subject.id,
                        academic_year=DEMO_ACADEMIC_YEAR,
                    )
                )


async def _ensure_grade_students(
    session: AsyncSession,
    school: School,
    grade_level: str,
    classes: Sequence[SchoolClass],
) -> list[list[Student]]:
    grade_tag = GRADE_TAGS[grade_level].upper()
    existing_students = list(
        (
            await session.scalars(
                select(Student).where(
                    Student.school_id == school.id,
                    Student.student_no.like(f"{grade_tag}-%"),
                )
            )
        ).all()
    )
    student_map = {student.student_no: student for student in existing_students}
    existing_memberships = list(
        (
            await session.scalars(
                select(ClassMembership).where(
                    ClassMembership.class_id.in_([school_class.id for school_class in classes])
                )
            )
        ).all()
    )
    membership_keys = {
        (item.student_id, item.class_id, item.academic_year) for item in existing_memberships
    }
    fake = Faker("zh_CN")
    fake.seed_instance(20260830 + (1 if grade_level == "初一" else 2))
    students_by_class: list[list[Student]] = []
    for class_index, school_class in enumerate(classes, start=1):
        class_students: list[Student] = []
        for seat in range(1, DEMO_STUDENTS_PER_CLASS + 1):
            student_no = f"{grade_tag}-{DEMO_ACADEMIC_YEAR[:4]}-{class_index:02d}-{seat:02d}"
            student = student_map.get(student_no)
            if student is None:
                student = Student(
                    school_id=school.id,
                    student_no=student_no,
                    display_name=fake.name(),
                )
                session.add(student)
                await session.flush()
                student_map[student_no] = student
            key = (student.id, school_class.id, DEMO_ACADEMIC_YEAR)
            if key not in membership_keys:
                session.add(
                    ClassMembership(
                        student_id=student.id,
                        class_id=school_class.id,
                        academic_year=DEMO_ACADEMIC_YEAR,
                    )
                )
                membership_keys.add(key)
            class_students.append(student)
        students_by_class.append(class_students)
    return students_by_class


async def _ensure_grade_scores(
    session: AsyncSession,
    classes: Sequence[SchoolClass],
    students_by_class: list[list[Student]],
    exams: Sequence[Exam],
    subjects: Sequence[Subject],
    random_seed: int,
) -> None:
    student_ids = [student.id for class_students in students_by_class for student in class_students]
    existing = list(
        (
            await session.scalars(
                select(ExamScore).where(ExamScore.student_id.in_(student_ids))
            )
        ).all()
    )
    score_keys = {(item.student_id, item.exam_id, item.subject_id) for item in existing}
    score_values = build_demo_score_values(
        students_by_class,
        len(exams),
        [subject.max_score for subject in subjects],
        random_seed=random_seed,
    )
    for class_index, school_class in enumerate(classes):
        for student in students_by_class[class_index]:
            for exam_index, exam in enumerate(exams):
                for subject_index, subject in enumerate(subjects):
                    key = (student.id, exam.id, subject.id)
                    if key in score_keys:
                        continue
                    session.add(
                        ExamScore(
                            student_id=student.id,
                            class_id=school_class.id,
                            exam_id=exam.id,
                            subject_id=subject.id,
                            score=score_values[(student.id, exam_index, subject_index)],
                        )
                    )


async def _ensure_grade_users(
    session: AsyncSession,
    school: School,
    grade_level: str,
    teachers: Sequence[Teacher],
    classes: Sequence[SchoolClass],
    students_by_class: list[list[Student]],
) -> None:
    tag = GRADE_TAGS[grade_level]
    usernames = [
        f"{tag}_student01",
        *[f"{tag}_teacher{index:02d}" for index in range(1, len(teachers) + 1)],
        *[f"{tag}_headteacher{index:02d}" for index in range(1, len(classes) + 1)],
    ]
    existing = set(
        (
            await session.scalars(select(User.username).where(User.username.in_(usernames)))
        ).all()
    )
    shared_hash = hash_password(settings.demo_password)
    if f"{tag}_student01" not in existing:
        session.add(
            User(
                school_id=school.id,
                username=f"{tag}_student01",
                password_hash=shared_hash,
                role=UserRole.STUDENT,
                student_id=students_by_class[0][0].id,
            )
        )
    for index, teacher in enumerate(teachers, start=1):
        username = f"{tag}_teacher{index:02d}"
        if username not in existing:
            session.add(
                User(
                    school_id=school.id,
                    username=username,
                    password_hash=shared_hash,
                    role=UserRole.SUBJECT_TEACHER,
                    teacher_id=teacher.id,
                )
            )
    for index, school_class in enumerate(classes, start=1):
        username = f"{tag}_headteacher{index:02d}"
        if username not in existing:
            session.add(
                User(
                    school_id=school.id,
                    username=username,
                    password_hash=shared_hash,
                    role=UserRole.HEAD_TEACHER,
                    teacher_id=school_class.head_teacher_id,
                )
            )


async def ensure_demo_grade_data(session: AsyncSession, school: School) -> None:
    """Idempotently enrich the demo school with separate grade-one/two datasets."""
    subjects_by_code = await _ensure_subjects(session, school)
    await _ensure_curriculum(session, school, subjects_by_code)
    for grade_level in ("初一", "初二"):
        subject_codes = GRADE_SUBJECT_CODES[grade_level]
        teachers, teachers_by_subject = await _ensure_grade_teachers(
            session, school, grade_level, subject_codes
        )
        classes = await _ensure_grade_classes(
            session, school, grade_level, teachers_by_subject
        )
        exams = await _ensure_grade_exams(session, school, grade_level)
        await _ensure_grade_assignments(
            session,
            classes,
            subjects_by_code,
            subject_codes,
            teachers_by_subject,
        )
        students_by_class = await _ensure_grade_students(
            session, school, grade_level, classes
        )
        subjects = [subjects_by_code[code] for code in subject_codes]
        await _ensure_grade_scores(
            session,
            classes,
            students_by_class,
            exams,
            subjects,
            random_seed=20260827 if grade_level == "初一" else 20260828,
        )
        await _ensure_grade_users(
            session, school, grade_level, teachers, classes, students_by_class
        )
    await session.commit()


async def reseed_additional_grade_scores(session: AsyncSession) -> int:
    """Refresh only grade-one/two demo scores with grade-specific random seeds."""
    school = await session.scalar(select(School).where(School.name == "格致实验学校"))
    if not school:
        return 0
    subjects_by_id = {
        item.id: item
        for item in (
            await session.scalars(select(Subject).where(Subject.school_id == school.id))
        ).all()
    }
    configs = list(
        (
            await session.scalars(
                select(GradeSubjectConfig).where(
                    GradeSubjectConfig.school_id == school.id,
                    GradeSubjectConfig.academic_year == DEMO_ACADEMIC_YEAR,
                )
            )
        ).all()
    )
    updated = 0
    affected_student_ids: list[int] = []
    for grade_level, random_seed in (("初一", 20260827), ("初二", 20260828)):
        classes = list(
            (
                await session.scalars(
                    select(SchoolClass)
                    .where(
                        SchoolClass.school_id == school.id,
                        SchoolClass.academic_year == DEMO_ACADEMIC_YEAR,
                        SchoolClass.grade_level == grade_level,
                    )
                    .order_by(SchoolClass.name)
                )
            ).all()
        )
        exams = list(
            (
                await session.scalars(
                    select(Exam)
                    .where(
                        Exam.school_id == school.id,
                        Exam.academic_year == DEMO_ACADEMIC_YEAR,
                        Exam.grade_level == grade_level,
                    )
                    .order_by(Exam.exam_date, Exam.id)
                )
            ).all()
        )
        grade_configs = sorted(
            (item for item in configs if item.grade_level == grade_level),
            key=lambda item: item.sort_order,
        )
        subjects = [subjects_by_id[item.subject_id] for item in grade_configs]
        memberships = list(
            (
                await session.scalars(
                    select(ClassMembership).where(
                        ClassMembership.class_id.in_([item.id for item in classes])
                    )
                )
            ).all()
        )
        students_by_id = {
            item.id: item
            for item in (
                await session.scalars(
                    select(Student).where(
                        Student.id.in_([item.student_id for item in memberships])
                    )
                )
            ).all()
        }
        students_by_class = [
            sorted(
                (
                    students_by_id[item.student_id]
                    for item in memberships
                    if item.class_id == school_class.id
                ),
                key=lambda student: student.student_no,
            )
            for school_class in classes
        ]
        score_values = build_demo_score_values(
            students_by_class,
            len(exams),
            [subject.max_score for subject in subjects],
            random_seed=random_seed,
        )
        scores = list(
            (
                await session.scalars(
                    select(ExamScore).where(
                        ExamScore.class_id.in_([item.id for item in classes])
                    )
                )
            ).all()
        )
        exam_indexes = {exam.id: index for index, exam in enumerate(exams)}
        subject_indexes = {subject.id: index for index, subject in enumerate(subjects)}
        for score in scores:
            exam_index = exam_indexes.get(score.exam_id)
            subject_index = subject_indexes.get(score.subject_id)
            if exam_index is None or subject_index is None:
                continue
            score.score = score_values[(score.student_id, exam_index, subject_index)]
            affected_student_ids.append(score.student_id)
            updated += 1
    if affected_student_ids:
        await session.execute(
            delete(RiskSnapshot).where(RiskSnapshot.student_id.in_(set(affected_student_ids)))
        )
    await session.commit()
    return updated


async def reseed_demo_scores(session: AsyncSession) -> int:
    classes = list((await session.scalars(select(SchoolClass).order_by(SchoolClass.id))).all())
    exams = list((await session.scalars(select(Exam).order_by(Exam.exam_date, Exam.id))).all())
    subjects = list((await session.scalars(select(Subject).order_by(Subject.id))).all())
    demo_schemes = {
        code: (max_score, pass_score)
        for code, _, max_score, pass_score in DEMO_SUBJECT_SCHEMES
    }
    for subject in subjects:
        if subject.code in demo_schemes:
            subject.max_score, subject.pass_score = demo_schemes[subject.code]
    memberships = list(
        (await session.scalars(select(ClassMembership).order_by(ClassMembership.class_id))).all()
    )
    students = {item.id: item for item in (await session.scalars(select(Student))).all()}
    students_by_class = [
        [
            students[item.student_id]
            for item in memberships
            if item.class_id == school_class.id and item.student_id in students
        ]
        for school_class in classes
    ]
    score_values = build_demo_score_values(
        students_by_class,
        len(exams),
        [subject.max_score for subject in subjects],
    )
    existing_scores = list((await session.scalars(select(ExamScore))).all())
    exam_indexes = {exam.id: index for index, exam in enumerate(exams)}
    subject_indexes = {subject.id: index for index, subject in enumerate(subjects)}
    updated = 0
    for score in existing_scores:
        exam_index = exam_indexes.get(score.exam_id)
        subject_index = subject_indexes.get(score.subject_id)
        if exam_index is None or subject_index is None:
            continue
        value = score_values.get((score.student_id, exam_index, subject_index))
        if value is not None:
            score.score = value
            updated += 1
    await session.execute(delete(RiskSnapshot))
    await session.commit()
    return updated


async def normalize_demo_teaching_assignments(session: AsyncSession) -> int:
    school = await session.scalar(select(School).where(School.name == "格致实验学校"))
    if not school:
        return 0
    classes = list(
        (
            await session.scalars(
                select(SchoolClass)
                .where(
                    SchoolClass.school_id == school.id,
                    SchoolClass.grade_level == DEMO_GRADE_LEVEL,
                    SchoolClass.academic_year == DEMO_ACADEMIC_YEAR,
                )
                .order_by(SchoolClass.id)
            )
        ).all()
    )
    subjects = list(
        (
            await session.scalars(
                select(Subject).where(Subject.school_id == school.id).order_by(Subject.id)
            )
        ).all()
    )
    teachers = list(
        (
            await session.scalars(
                select(Teacher)
                .where(
                    Teacher.school_id == school.id,
                    Teacher.teacher_no.like("T%"),
                )
                .order_by(Teacher.teacher_no)
            )
        ).all()
    )
    expected_teacher_count = sum(DEMO_SUBJECT_TEACHER_COUNTS.values())
    if len(teachers) < expected_teacher_count:
        raise RuntimeError("演示教师数量不足，无法按学科均衡分配教师")

    subjects_by_code = {subject.code: subject for subject in subjects}
    teachers_by_subject: dict[str, list[Teacher]] = {}
    teacher_offset = 0
    for code, _, _, _ in DEMO_SUBJECT_SCHEMES:
        teacher_count = DEMO_SUBJECT_TEACHER_COUNTS[code]
        teachers_by_subject[code] = teachers[teacher_offset : teacher_offset + teacher_count]
        teacher_offset += teacher_count

    class_ids = [school_class.id for school_class in classes]
    await session.execute(
        delete(TeachingAssignment).where(TeachingAssignment.class_id.in_(class_ids))
    )
    assignments = []
    for class_index, school_class in enumerate(classes):
        for code, subject_teachers in teachers_by_subject.items():
            subject = subjects_by_code.get(code)
            if not subject:
                continue
            assignments.append(
                TeachingAssignment(
                    teacher_id=_teacher_for_class(subject_teachers, class_index).id,
                    class_id=school_class.id,
                    subject_id=subject.id,
                    academic_year=school_class.academic_year,
                )
            )
    session.add_all(assignments)
    await session.commit()
    return len(assignments)
