from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="Aqbobek Lyceum Portal API", version="2.0.0")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_API_URL = os.getenv("OPENAI_API_URL", "https://api.openai.com/v1/chat/completions").strip()
BILIMCLASS_URL = os.getenv("BILIMCLASS_URL", "").strip()
BILIMCLASS_TOKEN = os.getenv("BILIMCLASS_TOKEN", "").strip()
APP_SECRET = os.getenv("APP_SECRET", "aqbobek-dev-secret").strip()
TOKEN_TTL_MIN = int(os.getenv("TOKEN_TTL_MIN", "240"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class NotificationHub:
    def __init__(self) -> None:
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        dead: List[WebSocket] = []
        message = json.dumps(payload, ensure_ascii=False)
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


HUB = NotificationHub()


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64u_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def hash_password(password: str, user_id: int) -> str:
    salt = f"aqbobek-{user_id}".encode("utf-8")
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return dk.hex()


def verify_password(user: Dict[str, Any], password: str) -> bool:
    expected = user.get("password_hash")
    if expected:
        return hmac.compare_digest(expected, hash_password(password, int(user["id"])))
    return hmac.compare_digest(str(user.get("password", "")), password)


def create_token(user: Dict[str, Any]) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": int(user["id"]),
        "role": user["role"],
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=TOKEN_TTL_MIN)).timestamp()),
    }
    payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    payload_b64 = _b64u(payload_json)
    sig = hmac.new(APP_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64u(sig)}"


def verify_token(authorization: str | None) -> Dict[str, Any]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload_b64, sig_b64 = token.split(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid token format")

    expected_sig = hmac.new(APP_SECRET.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64u(expected_sig), sig_b64):
        raise HTTPException(status_code=401, detail="Invalid token signature")

    try:
        payload = json.loads(_b64u_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    if int(payload.get("exp", 0)) < int(datetime.now(timezone.utc).timestamp()):
        raise HTTPException(status_code=401, detail="Token expired")
    return payload


def require_roles(authorization: str | None, allowed_roles: List[str]) -> Dict[str, Any]:
    payload = verify_token(authorization)
    role = str(payload.get("role", ""))
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return payload


def bootstrap_password_hashes() -> None:
    for user in DB["users"]:
        if "password_hash" not in user and "password" in user:
            user["password_hash"] = hash_password(str(user["password"]), int(user["id"]))

DB: Dict[str, Any] = {
    "users": [
        {"id": 1, "name": "Aruzhan S.", "role": "student", "grade_level": 10, "class_name": "10A", "email": "aruzhan.student@aqbobek.edu.kz", "password": "demo123"},
        {"id": 2, "name": "Maksat T.", "role": "student", "grade_level": 10, "class_name": "10A", "email": "maksat.student@aqbobek.edu.kz", "password": "demo123"},
        {"id": 3, "name": "Aigerim K.", "role": "student", "grade_level": 10, "class_name": "10B", "email": "aigerim.student@aqbobek.edu.kz", "password": "demo123"},
        {"id": 4, "name": "Mr. Nurlan", "role": "teacher", "subjects": ["Physics", "Math"], "email": "nurlan.teacher@aqbobek.edu.kz", "password": "demo123"},
        {"id": 5, "name": "Ms. Dana", "role": "teacher", "subjects": ["History"], "email": "dana.teacher@aqbobek.edu.kz", "password": "demo123"},
        {"id": 6, "name": "Parent of Aruzhan", "role": "parent", "child_id": 1, "email": "parent.aruzhan@gmail.com", "password": "demo123"},
        {"id": 7, "name": "Admin", "role": "admin", "email": "admin@aqbobek.edu.kz", "password": "demo123"},
        {"id": 8, "name": "Parent of Maksat", "role": "parent", "child_id": 2, "email": "parent.maksat@gmail.com", "password": "demo123"},
        {"id": 9, "name": "Parent of Aigerim", "role": "parent", "child_id": 3, "email": "parent.aigerim@gmail.com", "password": "demo123"},
    ],
    "grades": [
        {"student_id": 1, "subject": "Physics", "topic": "Kinematics", "score": 95, "max_score": 100, "date": "2026-03-01", "assessment_type": "FA"},
        {"student_id": 1, "subject": "Physics", "topic": "Dynamics", "score": 92, "max_score": 100, "date": "2026-03-08", "assessment_type": "FA"},
        {"student_id": 1, "subject": "Math", "topic": "Functions", "score": 97, "max_score": 100, "date": "2026-03-04", "assessment_type": "FA"},
        {"student_id": 1, "subject": "Math", "topic": "Trigonometry", "score": 91, "max_score": 100, "date": "2026-03-18", "assessment_type": "FA"},
        {"student_id": 1, "subject": "History", "topic": "Industrial Revolution", "score": 88, "max_score": 100, "date": "2026-03-10", "assessment_type": "FA"},
        {"student_id": 1, "subject": "Physics", "topic": "Q1 Quarter Grade", "score": 91, "max_score": 100, "date": "2026-01-15", "assessment_type": "QUARTER"},
        {"student_id": 1, "subject": "Physics", "topic": "Q2 Quarter Grade", "score": 93, "max_score": 100, "date": "2026-02-15", "assessment_type": "QUARTER"},
        {"student_id": 1, "subject": "Math", "topic": "Q1 Quarter Grade", "score": 94, "max_score": 100, "date": "2026-01-15", "assessment_type": "QUARTER"},
        {"student_id": 1, "subject": "Math", "topic": "Q2 Quarter Grade", "score": 96, "max_score": 100, "date": "2026-02-15", "assessment_type": "QUARTER"},
        {"student_id": 1, "subject": "History", "topic": "Q1 Quarter Grade", "score": 87, "max_score": 100, "date": "2026-01-15", "assessment_type": "QUARTER"},
        {"student_id": 1, "subject": "History", "topic": "Q2 Quarter Grade", "score": 90, "max_score": 100, "date": "2026-02-15", "assessment_type": "QUARTER"},

        {"student_id": 2, "subject": "Physics", "topic": "Kinematics", "score": 74, "max_score": 100, "date": "2026-03-01", "assessment_type": "FA"},
        {"student_id": 2, "subject": "Physics", "topic": "Dynamics", "score": 69, "max_score": 100, "date": "2026-03-08", "assessment_type": "FA"},
        {"student_id": 2, "subject": "Math", "topic": "Functions", "score": 48, "max_score": 100, "date": "2026-03-04", "assessment_type": "FA"},
        {"student_id": 2, "subject": "Math", "topic": "Trigonometry", "score": 41, "max_score": 100, "date": "2026-03-18", "assessment_type": "FA"},
        {"student_id": 2, "subject": "Math", "topic": "Algebra: Equations", "score": 44, "max_score": 100, "date": "2026-03-25", "assessment_type": "SA"},
        {"student_id": 2, "subject": "History", "topic": "Industrial Revolution", "score": 72, "max_score": 100, "date": "2026-03-10", "assessment_type": "FA"},
        {"student_id": 2, "subject": "Math", "topic": "Q1 Quarter Grade", "score": 58, "max_score": 100, "date": "2026-01-15", "assessment_type": "QUARTER"},
        {"student_id": 2, "subject": "Math", "topic": "Q2 Quarter Grade", "score": 52, "max_score": 100, "date": "2026-02-15", "assessment_type": "QUARTER"},
        {"student_id": 2, "subject": "Math", "topic": "Q3 Quarter Grade", "score": 44, "max_score": 100, "date": "2026-03-28", "assessment_type": "QUARTER"},
        {"student_id": 2, "subject": "Physics", "topic": "Q1 Quarter Grade", "score": 72, "max_score": 100, "date": "2026-01-15", "assessment_type": "QUARTER"},
        {"student_id": 2, "subject": "Physics", "topic": "Q2 Quarter Grade", "score": 70, "max_score": 100, "date": "2026-02-15", "assessment_type": "QUARTER"},
        {"student_id": 2, "subject": "History", "topic": "Q1 Quarter Grade", "score": 75, "max_score": 100, "date": "2026-01-15", "assessment_type": "QUARTER"},
        {"student_id": 2, "subject": "History", "topic": "Q2 Quarter Grade", "score": 71, "max_score": 100, "date": "2026-02-15", "assessment_type": "QUARTER"},

        {"student_id": 3, "subject": "Physics", "topic": "Kinematics", "score": 58, "max_score": 100, "date": "2026-03-01", "assessment_type": "FA"},
        {"student_id": 3, "subject": "Physics", "topic": "Dynamics", "score": 49, "max_score": 100, "date": "2026-03-08", "assessment_type": "FA"},
        {"student_id": 3, "subject": "Physics", "topic": "Electricity", "score": 43, "max_score": 100, "date": "2026-03-15", "assessment_type": "FA"},
        {"student_id": 3, "subject": "Math", "topic": "Functions", "score": 61, "max_score": 100, "date": "2026-03-04", "assessment_type": "FA"},
        {"student_id": 3, "subject": "Math", "topic": "Trigonometry", "score": 55, "max_score": 100, "date": "2026-03-18", "assessment_type": "FA"},
        {"student_id": 3, "subject": "History", "topic": "Industrial Revolution", "score": 63, "max_score": 100, "date": "2026-03-10", "assessment_type": "FA"},
    ],
    "attendance": [
        {"student_id": 1, "subject": "Physics", "date": "2026-03-20", "status": "present"},
        {"student_id": 1, "subject": "History", "date": "2026-03-21", "status": "present"},

        {"student_id": 2, "subject": "Math", "date": "2026-03-17", "status": "absent"},
        {"student_id": 2, "subject": "Physics", "date": "2026-03-20", "status": "present"},

        {"student_id": 3, "subject": "History", "date": "2026-03-12", "status": "absent"},
        {"student_id": 3, "subject": "History", "date": "2026-03-19", "status": "absent"},
        {"student_id": 3, "subject": "Physics", "date": "2026-03-22", "status": "absent"},
    ],
    "achievements": [
        {"id": 1, "student_id": 1, "title": "Regional Physics Olympiad", "level": "Regional", "verified": True, "date": "2026-02-10", "place": "1st Place", "description": "Победитель регионального этапа по физике среди учеников 10-11 классов"},
        {"id": 2, "student_id": 1, "title": "Debate Championship 'Uaqyt'", "level": "School", "verified": True, "date": "2026-01-22", "place": "1st Place", "description": "Лучший спикер финала школьного дебатного турнира"},
        {"id": 3, "student_id": 1, "title": "National Science Fair — Biology", "level": "National", "verified": True, "date": "2025-11-15", "place": "3rd Place", "description": "Исследовательская работа 'Влияние стресса на рост растений'"},
        {"id": 4, "student_id": 2, "title": "Math Marathon 'Sanaq'", "level": "School", "verified": True, "date": "2026-03-05", "place": "2nd Place", "description": "Второе место в командном марафоне по математике"},
        {"id": 5, "student_id": 2, "title": "Creative Coding Hackathon", "level": "City", "verified": False, "date": "2026-02-18", "place": "Participant", "description": "Участник городского хакатона по программированию"},
        {"id": 6, "student_id": 3, "title": "Volunteer Day — City Cleanup", "level": "School", "verified": False, "date": "2026-02-20", "place": "Participant", "description": "Участие в городском экологическом волонтёрском мероприятии"},
    ],
    "teacher_feedback": [
        {"student_id": 1, "subject": "Physics", "teacher": "Mr. Nurlan", "comment": "Показывает высокий уровень понимания тем и быстро схватывает новые концепции."},
        {"student_id": 1, "subject": "Math", "teacher": "Mr. Nurlan", "comment": "Стабильно сильный результат, особенно в задачах повышенной сложности."},
        {"student_id": 1, "subject": "History", "teacher": "Ms. Dana", "comment": "Хорошо анализирует события и уверенно работает с аргументацией."},

        {"student_id": 2, "subject": "Physics", "teacher": "Mr. Nurlan", "comment": "Работает уверенно, но нуждается в большей регулярности при повторении формул."},
        {"student_id": 2, "subject": "Math", "teacher": "Mr. Nurlan", "comment": "Средний уровень. Может улучшиться при систематической практике."},
        {"student_id": 2, "subject": "History", "teacher": "Ms. Dana", "comment": "Понимание тем есть, но иногда не хватает глубины в ответах."},

        {"student_id": 3, "subject": "Physics", "teacher": "Mr. Nurlan", "comment": "Есть существенные пробелы в базовых темах, требуется индивидуальная консультация."},
        {"student_id": 3, "subject": "Math", "teacher": "Mr. Nurlan", "comment": "Часто испытывает трудности в применении формул на практике."},
        {"student_id": 3, "subject": "History", "teacher": "Ms. Dana", "comment": "Пропуски отрицательно влияют на понимание материала и качество ответов."},
    ],
    "posts": [
        {"id": 1, "title": "SAT Workshop", "body": "Free workshop this Friday in room 204.", "target": ["10", "11"], "created_at": "2026-03-25T08:00:00"},
        {"id": 2, "title": "Spring Charity Fair", "body": "All parents are invited to the spring fair.", "target": ["all"], "created_at": "2026-03-26T09:30:00"},
    ],
    "notifications": [],
    "teachers": [
        {"teacher_id": 4, "availability": {"Mon": [1, 2, 3, 4, 5], "Tue": [1, 2, 3, 4], "Wed": [1, 2, 3, 4, 5], "Thu": [2, 3, 4, 5], "Fri": [1, 2, 3]}},
        {"teacher_id": 5, "availability": {"Mon": [1, 2, 4, 5], "Tue": [1, 2, 3, 5], "Wed": [1, 3, 4], "Thu": [1, 2, 3, 4, 5], "Fri": [1, 2, 3, 4]}},
    ],
    "rooms": [
        {"name": "Physics Lab", "type": "lab"},
        {"name": "Math 101", "type": "classroom"},
        {"name": "History 203", "type": "classroom"},
        {"name": "Assembly Hall", "type": "event"},
    ],
    "schedule_requirements": [
        {"class_name": "10A", "subject": "Physics", "teacher_id": 4, "room_type": "lab", "weekly_slots": 2, "session_type": "lesson"},
        {"class_name": "10A", "subject": "Math", "teacher_id": 4, "room_type": "classroom", "weekly_slots": 3, "session_type": "lesson"},
        {"class_name": "10A", "subject": "History", "teacher_id": 5, "room_type": "classroom", "weekly_slots": 2, "session_type": "lesson"},
        {"class_name": "10B", "subject": "Physics", "teacher_id": 4, "room_type": "lab", "weekly_slots": 2, "session_type": "lesson"},
        {"class_name": "10B", "subject": "History", "teacher_id": 5, "room_type": "classroom", "weekly_slots": 2, "session_type": "lesson"},
        {"class_name": "10A", "subject": "Math Practice Pair", "teacher_id": 4, "room_type": "classroom", "weekly_slots": 1, "session_type": "pair"},
        {"class_name": "10B", "subject": "Advisory Hour", "teacher_id": 5, "room_type": "classroom", "weekly_slots": 1, "session_type": "academic_hour"},
        {"class_name": "10A", "subject": "Lyceum Assembly", "teacher_id": 5, "room_type": "event", "weekly_slots": 1, "session_type": "event"},
        {
            "class_name": "10A+10B",
            "subject": "Profile Stream",
            "teacher_id": 4,
            "room_type": "classroom",
            "weekly_slots": 1,
            "session_type": "stream",
            "groups": [
                {"group_name": "Physics Advanced", "teacher_id": 4, "room_type": "lab"},
                {"group_name": "Humanities Seminar", "teacher_id": 5, "room_type": "classroom"},
            ],
        },
    ],
    "generated_schedule": [],
}

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
SLOTS = [1, 2, 3, 4, 5, 6]
bootstrap_password_hashes()


class LoginRequest(BaseModel):
    user_id: int
    password: str


class PostCreate(BaseModel):
    title: str
    body: str
    target: List[str] = Field(default_factory=lambda: ["all"])


class TeacherSickRequest(BaseModel):
    teacher_id: int
    sick_day: str


class AIReportResponse(BaseModel):
    risk_score: float
    risk_level: str
    failing_probability: float
    weak_topics: List[str]
    recommendations: List[str]
    summary: str


def get_user(user_id: int) -> Dict[str, Any]:
    user = next((u for u in DB["users"] if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


def sanitize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in user.items() if k not in {"password", "password_hash"}}


def grades_for_student(student_id: int) -> List[Dict[str, Any]]:
    return [g for g in DB["grades"] if g["student_id"] == student_id]


def attendance_for_student(student_id: int) -> List[Dict[str, Any]]:
    return [a for a in DB["attendance"] if a["student_id"] == student_id]


def achievements_for_student(student_id: int) -> List[Dict[str, Any]]:
    return [a for a in DB["achievements"] if a["student_id"] == student_id]


def feedback_for_student(student_id: int) -> List[Dict[str, Any]]:
    return [f for f in DB["teacher_feedback"] if f["student_id"] == student_id]


def teacher_email_by_name(name: str) -> str:
    teacher = next((u for u in DB["users"] if u["role"] == "teacher" and u["name"] == name), None)
    return (teacher or {}).get("email", "—")


def parent_contacts_for_student(student_id: int) -> List[Dict[str, str]]:
    parents = [u for u in DB["users"] if u["role"] == "parent" and u.get("child_id") == student_id]
    return [{"name": p.get("name", "Parent"), "email": p.get("email", "—")} for p in parents]


def average(values: List[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def call_openai_json(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Dict[str, Any] | None:
    if not OPENAI_API_KEY:
        return None

    payload = {
        "model": OPENAI_MODEL,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urlrequest.Request(
        OPENAI_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
    except Exception:
        return None


def fetch_bilimclass_grades(student_id: int) -> List[Dict[str, Any]]:
    """
    Fetch grades from real BilimClass-like API if BILIMCLASS_URL is set.
    Expected shape: {"grades":[...]}.
    Falls back to local mock DB data if unavailable.
    """
    if not BILIMCLASS_URL:
        return grades_for_student(student_id)

    url = f"{BILIMCLASS_URL.rstrip('/')}/grades?student_id={student_id}"
    req = urlrequest.Request(url, method="GET")
    if BILIMCLASS_TOKEN:
        req.add_header("Authorization", f"Bearer {BILIMCLASS_TOKEN}")

    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        grades = data.get("grades")
        if isinstance(grades, list) and grades:
            return grades
    except (urlerror.URLError, TimeoutError, ValueError, KeyError):
        pass
    return grades_for_student(student_id)


def compute_student_ai_report(student_id: int) -> Dict[str, Any]:
    student_grades = fetch_bilimclass_grades(student_id)
    if not student_grades:
        return {
            "risk_score": 0,
            "risk_level": "low",
            "failing_probability": 0,
            "weak_topics": [],
            "recommendations": ["No data yet"],
            "summary": "Недостаточно данных для анализа.",
        }

    subject_scores: Dict[str, List[float]] = defaultdict(list)
    topic_scores: List[Tuple[str, float]] = []
    recent_penalty = 0.0

    sorted_grades = sorted(student_grades, key=lambda x: x["date"])
    for idx, g in enumerate(sorted_grades):
        pct = (g["score"] / g["max_score"]) * 100
        subject_scores[g["subject"]].append(pct)
        topic_scores.append((f"{g['subject']}: {g['topic']}", pct))

        if idx > 0:
            prev = (sorted_grades[idx - 1]["score"] / sorted_grades[idx - 1]["max_score"]) * 100
            if pct < prev - 12:
                recent_penalty += 7

    weak_topics = [name for name, pct in sorted(topic_scores, key=lambda x: x[1])[:3] if pct < 70]
    low_score_penalty = sum(max(0, 70 - pct) * 0.8 for _, pct in topic_scores)

    absence_count = sum(1 for a in attendance_for_student(student_id) if a["status"] == "absent")
    attendance_penalty = absence_count * 9

    risk_score = min(100.0, round(low_score_penalty + recent_penalty + attendance_penalty, 2))
    failing_probability = min(95.0, round(15 + risk_score * 0.8, 2)) if risk_score > 0 else 5.0

    # Math-specific exam failure prediction
    math_scores = subject_scores.get("Math", [])
    math_avg = average(math_scores) if math_scores else None
    math_exam_fail_prob = None
    if math_avg is not None and math_avg < 60:
        # Trend: if last math score worse than average, increase risk
        math_trend_penalty = 0
        math_grade_list = sorted([g for g in student_grades if g["subject"] == "Math"], key=lambda x: x["date"])
        if len(math_grade_list) >= 2:
            last = (math_grade_list[-1]["score"] / math_grade_list[-1]["max_score"]) * 100
            prev = (math_grade_list[-2]["score"] / math_grade_list[-2]["max_score"]) * 100
            if last < prev:
                math_trend_penalty = 15
        math_exam_fail_prob = min(92.0, round(55 + (60 - math_avg) * 1.2 + math_trend_penalty, 1))

    if risk_score >= 65:
        risk_level = "high"
    elif risk_score >= 30:
        risk_level = "medium"
    else:
        risk_level = "low"

    recommendations = []
    if weak_topics:
        recommendations.append(f"Повторить темы: {', '.join(weak_topics)}")
    if absence_count:
        recommendations.append(f"Снизить количество пропусков: сейчас {absence_count} отсутствий")
    weakest_subject = min(subject_scores.items(), key=lambda x: average(x[1]))[0]
    recommendations.append(f"Сделать 3 targeted practice задания по предмету {weakest_subject}")
    recommendations.append("Пройти короткий мини-квиз и посмотреть 2 видеолекции до конца недели")
    if math_exam_fail_prob is not None:
        recommendations.append(f"🚨 Критично: записаться на дополнительные занятия по математике — текущий уровень ({round(math_avg)}%) недостаточен")

    summary = (
        f"С вероятностью {int(failing_probability)}% ученик может столкнуться с трудностями "
        f"на следующем суммативе, если не закрыть пробелы. Основной риск связан с предметом {weakest_subject}."
    )
    if math_exam_fail_prob is not None:
        summary += (
            f" ⚠️ AI-прогноз по математике: вероятность провала экзамена — {int(math_exam_fail_prob)}%. "
            f"Средний балл по математике ({round(math_avg)}%) значительно ниже порогового значения."
        )

    llm_used = False
    llm_resp = call_openai_json(
        system_prompt=(
            "You are an education analyst. Return JSON with keys: summary, recommendations. "
            "recommendations must be an array of 3 concise actionable items."
        ),
        user_prompt=(
            f"Student risk_level={risk_level}, risk_score={risk_score}, fail_probability={failing_probability}, "
            f"math_exam_fail_prob={math_exam_fail_prob}, weak_topics={weak_topics}, absences={absence_count}, "
            f"weakest_subject={weakest_subject}. Write in Russian."
        ),
    )
    if llm_resp and isinstance(llm_resp, dict):
        llm_summary = llm_resp.get("summary")
        llm_recs = llm_resp.get("recommendations")
        if isinstance(llm_summary, str) and llm_summary.strip():
            summary = llm_summary.strip()
            llm_used = True
        if isinstance(llm_recs, list):
            recs = [str(x).strip() for x in llm_recs if str(x).strip()]
            if recs:
                recommendations = recs[:5]
                llm_used = True

    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "failing_probability": failing_probability,
        "math_exam_fail_prob": math_exam_fail_prob,
        "weak_topics": weak_topics,
        "recommendations": recommendations,
        "summary": summary,
        "llm_used": llm_used,
    }


def build_leaderboard() -> List[Dict[str, Any]]:
    students = [u for u in DB["users"] if u["role"] == "student"]
    result = []

    for s in students:
        grades = fetch_bilimclass_grades(s["id"])
        avg = average([(g["score"] / g["max_score"]) * 100 for g in grades])
        achievements = len(achievements_for_student(s["id"]))
        score = round(avg + achievements * 2, 2)
        result.append({
            "student_id": s["id"],
            "name": s["name"],
            "score": score,
            "average_grade": avg,
        })

    return sorted(result, key=lambda x: x["score"], reverse=True)


def teacher_early_warning(teacher_id: int) -> List[Dict[str, Any]]:
    teacher = get_user(teacher_id)
    subjects = teacher.get("subjects", [])
    warnings = []

    for student in [u for u in DB["users"] if u["role"] == "student"]:
        report = compute_student_ai_report(student["id"])
        relevant = [g for g in fetch_bilimclass_grades(student["id"]) if g["subject"] in subjects]

        if relevant:
            contacts = parent_contacts_for_student(student["id"])
            warnings.append({
                "student_id": student["id"],
                "student_name": student["name"],
                "class_name": student["class_name"],
                "risk_level": report["risk_level"],
                "risk_score": report["risk_score"],
                "weak_topics": report["weak_topics"],
                "parent_contacts": contacts,
                "parent_emails": [c["email"] for c in contacts],
            })

    return sorted(warnings, key=lambda x: x["risk_score"], reverse=True)


def generate_teacher_report(teacher_id: int) -> str:
    warnings = teacher_early_warning(teacher_id)
    if not warnings:
        return "No class data available for report generation."

    lines = ["Auto-generated class risk report:"]
    for w in warnings:
        lines.append(
            f"- {w['student_name']} ({w['class_name']}): risk {w['risk_level']} ({w['risk_score']}). "
            f"Weak topics: {', '.join(w['weak_topics']) if w['weak_topics'] else 'none detected'}."
        )
    lines.append("Recommended strategy: extension tasks for strong students, targeted practice for middle group, and consultations for high-risk students.")
    fallback = "\n".join(lines)

    llm_resp = call_openai_json(
        system_prompt="You are a school methodology assistant. Return JSON with key report.",
        user_prompt=f"Create a concise principal-ready class report from this warning list: {warnings}. Language: Russian.",
        temperature=0.1,
    )
    if llm_resp and isinstance(llm_resp, dict):
        report = llm_resp.get("report")
        if isinstance(report, str) and report.strip():
            return report.strip()
    return fallback


def global_admin_radar() -> Dict[str, Any]:
    students = [u for u in DB["users"] if u["role"] == "student"]
    by_class: Dict[str, List[float]] = defaultdict(list)
    by_subject: Dict[str, List[float]] = defaultdict(list)
    risk_distribution = {"low": 0, "medium": 0, "high": 0}

    for s in students:
        student_grades = fetch_bilimclass_grades(s["id"])
        avg = average([(g["score"] / g["max_score"]) * 100 for g in student_grades])
        by_class[s["class_name"]].append(avg)

        for g in student_grades:
            by_subject[g["subject"]].append((g["score"] / g["max_score"]) * 100)

        risk_distribution[compute_student_ai_report(s["id"])["risk_level"]] += 1

    return {
        "class_averages": {k: average(v) for k, v in by_class.items()},
        "subject_averages": {k: average(v) for k, v in by_subject.items()},
        "risk_distribution": risk_distribution,
    }


def room_candidates(room_type: str) -> List[str]:
    exact = [r["name"] for r in DB["rooms"] if r["type"] == room_type]
    if exact:
        return exact
    return [r["name"] for r in DB["rooms"]]


def teacher_available(teacher_id: int, day: str, slot: int) -> bool:
    record = next((t for t in DB["teachers"] if t["teacher_id"] == teacher_id), None)
    return bool(record and slot in record["availability"].get(day, []))


def generate_schedule() -> List[Dict[str, Any]]:
    teacher_busy: Dict[Tuple[int, str, int], bool] = {}
    room_busy: Dict[Tuple[str, str, int], bool] = {}
    class_busy: Dict[Tuple[str, str, int], bool] = {}
    schedule: List[Dict[str, Any]] = []

    requirements = sorted(
        DB["schedule_requirements"],
        key=lambda x: 0 if x.get("session_type") == "stream" else 1
    )

    for req in requirements:
        slots_needed = req["weekly_slots"]
        assigned = 0
        class_targets = req["class_name"].split("+")

        for day in DAYS:
            for slot in SLOTS:
                if assigned >= slots_needed:
                    break

                if req.get("session_type") == "stream":
                    groups = req.get("groups", [])
                    can_place = True
                    temp_entries = []

                    for group in groups:
                        teacher_id = group["teacher_id"]

                        if not teacher_available(teacher_id, day, slot) or teacher_busy.get((teacher_id, day, slot)):
                            can_place = False
                            break

                        room = next(
                            (r for r in room_candidates(group["room_type"]) if not room_busy.get((r, day, slot))),
                            None
                        )
                        if not room:
                            can_place = False
                            break

                        for class_name in class_targets:
                            if class_busy.get((class_name, day, slot)):
                                can_place = False
                                break

                        if not can_place:
                            break

                        temp_entries.append({
                            "day": day,
                            "slot": slot,
                            "class_name": req["class_name"],
                            "subject": req["subject"],
                            "group_name": group["group_name"],
                            "teacher_id": teacher_id,
                            "room": room,
                            "session_type": "stream",
                        })

                    if can_place:
                        for entry in temp_entries:
                            teacher_busy[(entry["teacher_id"], day, slot)] = True
                            room_busy[(entry["room"], day, slot)] = True

                        for class_name in class_targets:
                            class_busy[(class_name, day, slot)] = True

                        schedule.extend(temp_entries)
                        assigned += 1

                else:
                    teacher_id = req["teacher_id"]

                    if not teacher_available(teacher_id, day, slot) or teacher_busy.get((teacher_id, day, slot)):
                        continue
                    if class_busy.get((req["class_name"], day, slot)):
                        continue

                    room = next(
                        (r for r in room_candidates(req["room_type"]) if not room_busy.get((r, day, slot))),
                        None
                    )
                    if not room:
                        continue

                    entry = {
                        "day": day,
                        "slot": slot,
                        "class_name": req["class_name"],
                        "subject": req["subject"],
                        "teacher_id": teacher_id,
                        "room": room,
                        "session_type": req.get("session_type", "lesson"),
                    }

                    teacher_busy[(teacher_id, day, slot)] = True
                    class_busy[(req["class_name"], day, slot)] = True
                    room_busy[(room, day, slot)] = True
                    schedule.append(entry)
                    assigned += 1

            if assigned >= slots_needed:
                break

        if assigned < slots_needed:
            schedule.append({
                "day": "UNASSIGNED",
                "slot": 0,
                "class_name": req["class_name"],
                "subject": req["subject"],
                "teacher_id": req.get("teacher_id"),
                "room": None,
                "session_type": "unassigned",
                "missing_slots": slots_needed - assigned,
            })

    DB["generated_schedule"] = schedule
    return schedule


def reschedule_for_sick_teacher(teacher_id: int, sick_day: str) -> Dict[str, Any]:
    base_schedule = DB["generated_schedule"] or generate_schedule()
    affected = [e for e in base_schedule if e.get("teacher_id") == teacher_id and e.get("day") == sick_day]

    if not affected:
        return {
            "affected_lessons": [],
            "notifications": [],
            "message": "No lessons affected on this day."
        }

    replacement_teachers = [
        u for u in DB["users"]
        if u["role"] == "teacher" and u["id"] != teacher_id
    ]

    notifications = []

    for entry in affected:
        replacement = next(
            (t for t in replacement_teachers if teacher_available(t["id"], sick_day, entry["slot"])),
            None
        )
        old_teacher = entry["teacher_id"]

        if replacement:
            entry["teacher_id"] = replacement["id"]
            note = (
                f"Замена: {entry['subject']} для {entry['class_name']} "
                f"в {sick_day} слот {entry['slot']} теперь ведет {replacement['name']}."
            )
        else:
            entry["subject"] = f"CANCELLED / {entry['subject']}"
            note = (
                f"Отмена: {entry['class_name']} {sick_day} слот {entry['slot']} — "
                f"преподаватель заболел, замена не найдена."
            )

        notifications.append({
            "message": note,
            "created_at": datetime.utcnow().isoformat(),
        })

        DB["notifications"].append({
            "id": len(DB["notifications"]) + 1,
            "message": note,
            "audience": [entry["class_name"]],
            "created_at": datetime.utcnow().isoformat(),
        })

        entry["original_teacher_id"] = old_teacher

    return {
        "affected_lessons": affected,
        "notifications": notifications,
        "message": "Schedule updated",
    }


@app.get("/")
def root() -> Dict[str, str]:
    return {"message": "Aqbobek Lyceum Portal API is running"}


@app.get("/api/bilimclass/grades")
def bilimclass_grades(student_id: int) -> Dict[str, Any]:
    """
    Unified grade endpoint:
    - Reads from external BilimClass-compatible endpoint if configured
    - Falls back to local mock DB grades
    """
    return {"student_id": student_id, "grades": fetch_bilimclass_grades(student_id)}


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> Dict[str, Any]:
    user = get_user(payload.user_id)
    if not verify_password(user, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    safe_user = sanitize_user(user)
    token = create_token(user)
    return {
        "token": token,
        "token_type": "bearer",
        "expires_in_minutes": TOKEN_TTL_MIN,
        "user": safe_user,
    }


@app.get("/api/student/{student_id}/dashboard")
def student_dashboard(student_id: int, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    payload = require_roles(authorization, ["student", "parent", "teacher", "admin"])
    student = get_user(student_id)
    if student["role"] != "student":
        raise HTTPException(status_code=400, detail="Not a student")
    if payload["role"] == "student" and int(payload["sub"]) != student_id:
        raise HTTPException(status_code=403, detail="Students can view only their own dashboard")

    grades = fetch_bilimclass_grades(student_id)
    attendance = attendance_for_student(student_id)
    ai_report = compute_student_ai_report(student_id)
    subject_summary = defaultdict(list)

    for g in grades:
        subject_summary[g["subject"]].append((g["score"] / g["max_score"]) * 100)

    safe_student = sanitize_user(student)

    return {
        "student": safe_student,
        "subject_summary": {k: average(v) for k, v in subject_summary.items()},
        "grades": grades,
        "attendance": attendance,
        "portfolio": achievements_for_student(student_id),
        "feedback": feedback_for_student(student_id),
        "leaderboard": build_leaderboard(),
        "ai_report": ai_report,
    }


@app.get("/api/student/{student_id}/ai-report", response_model=AIReportResponse)
def student_ai_report(student_id: int, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    payload = require_roles(authorization, ["student", "parent", "teacher", "admin"])
    if payload["role"] == "student" and int(payload["sub"]) != student_id:
        raise HTTPException(status_code=403, detail="Students can view only their own report")
    return compute_student_ai_report(student_id)


@app.get("/api/teacher/{teacher_id}/dashboard")
def teacher_dashboard(teacher_id: int, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    payload = require_roles(authorization, ["teacher", "admin"])
    teacher = get_user(teacher_id)
    if teacher["role"] != "teacher":
        raise HTTPException(status_code=400, detail="Not a teacher")
    if payload["role"] == "teacher" and int(payload["sub"]) != teacher_id:
        raise HTTPException(status_code=403, detail="Teachers can view only their own dashboard")

    safe_teacher = sanitize_user(teacher)

    return {
        "teacher": safe_teacher,
        "warnings": teacher_early_warning(teacher_id),
        "generated_report": generate_teacher_report(teacher_id),
    }


@app.get("/api/parent/{parent_id}/dashboard")
def parent_dashboard(parent_id: int, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    payload = require_roles(authorization, ["parent", "admin"])
    parent = get_user(parent_id)
    if parent["role"] != "parent":
        raise HTTPException(status_code=400, detail="Not a parent")
    if payload["role"] == "parent" and int(payload["sub"]) != parent_id:
        raise HTTPException(status_code=403, detail="Parents can view only their own dashboard")

    child_id = parent["child_id"]
    child = get_user(child_id)
    report = compute_student_ai_report(child_id)
    absences = sum(1 for a in attendance_for_student(child_id) if a["status"] == "absent")

    weekly_summary = (
        f"{child['name']} имеет академический статус '{report['risk_level']}', "
        f"risk score {report['risk_score']} и {absences} пропуск(а/ов). "
        f"Рекомендуется обратить внимание на: {', '.join(report['weak_topics']) if report['weak_topics'] else 'поддержание текущего уровня'}."
    )

    safe_parent = sanitize_user(parent)
    safe_child = sanitize_user(child)
    enriched_feedback = [
        {
            **f,
            "teacher_email": teacher_email_by_name(f.get("teacher", "")),
        }
        for f in feedback_for_student(child_id)
    ]

    return {
        "parent": safe_parent,
        "child": safe_child,
        "child_dashboard": student_dashboard(child_id, authorization=authorization),
        "teacher_feedback": enriched_feedback,
        "weekly_summary": weekly_summary,
    }


@app.get("/api/schedule/public")
def public_schedule(authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    require_roles(authorization, ["student", "teacher", "parent", "admin"])
    """Публичное расписание и замены — доступно всем ролям без авторизации."""
    schedule = DB["generated_schedule"] or generate_schedule()
    notifications = DB["notifications"][-10:]
    return {
        "schedule": schedule,
        "notifications": notifications,
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.get("/api/admin/dashboard")
def admin_dashboard(authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    require_roles(authorization, ["admin"])
    return {
        "radar": global_admin_radar(),
        "posts": DB["posts"],
        "notifications": DB["notifications"],
        "schedule": DB["generated_schedule"] or generate_schedule(),
    }


@app.post("/api/admin/posts")
async def create_post(payload: PostCreate, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    require_roles(authorization, ["admin"])
    post = {
        "id": len(DB["posts"]) + 1,
        "title": payload.title,
        "body": payload.body,
        "target": payload.target,
        "created_at": datetime.utcnow().isoformat(),
    }
    DB["posts"].append(post)
    await HUB.broadcast({"type": "post_created", "post": post})
    return post


@app.post("/api/schedule/generate")
async def generate_schedule_endpoint(authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    require_roles(authorization, ["admin"])
    schedule = generate_schedule()
    await HUB.broadcast({"type": "schedule_generated", "count": len(schedule)})
    return {"schedule": schedule}


@app.post("/api/schedule/teacher-sick")
async def teacher_sick(payload: TeacherSickRequest, authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    require_roles(authorization, ["admin"])
    result = reschedule_for_sick_teacher(payload.teacher_id, payload.sick_day)
    await HUB.broadcast(
        {
            "type": "teacher_sick_reschedule",
            "teacher_id": payload.teacher_id,
            "sick_day": payload.sick_day,
            "notifications": result.get("notifications", []),
        }
    )
    return result


@app.get("/api/kiosk-feed")
def kiosk_feed(authorization: str | None = Header(default=None)) -> Dict[str, Any]:
    require_roles(authorization, ["student", "teacher", "parent", "admin"])
    leaderboard = build_leaderboard()[:3]
    # Unified announcements: merge posts + schedule notifications, newest first
    posts = sorted(DB["posts"], key=lambda x: x["created_at"], reverse=True)
    notifications = sorted(DB["notifications"], key=lambda x: x["created_at"], reverse=True)
    # Return them separately so kiosk can style them differently
    return {
        "top_students": leaderboard,
        "schedule_updates": notifications[:5],
        "announcements": posts[:5],
        "generated_at": datetime.utcnow().isoformat(),
    }


@app.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket) -> None:
    token = websocket.query_params.get("token", "").strip()
    try:
        verify_token(f"Bearer {token}")
    except HTTPException:
        await websocket.close(code=1008)
        return
    await HUB.connect(websocket)
    try:
        await websocket.send_text(
            json.dumps(
                {"type": "connected", "message": "WebSocket notifications active"},
                ensure_ascii=False,
            )
        )
        while True:
            # Keep connection alive; we don't need client messages right now.
            await websocket.receive_text()
    except WebSocketDisconnect:
        HUB.disconnect(websocket)
