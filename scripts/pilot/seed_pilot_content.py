"""Populate the pilot course runs (one per test institution) with controlled sample content.

Idempotent: re-running replaces the sections of each pilot course and re-applies settings.
Run (Studio side, needs the course image files copied into the container first — see pilot.sh):

    tutor local run cms ./manage.py cms shell < scripts/pilot/seed_pilot_content.py
"""
from datetime import datetime, timezone
from pathlib import Path

from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey
from xmodule.contentstore.content import StaticContent
from xmodule.contentstore.django import contentstore
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import DuplicateCourseError

IMAGE_DIR = Path("/tmp/pilot-images")

def choice(prompt, options, correct):
    opts = "".join(
        f'<choice correct="{"true" if i == correct else "false"}">{o}</choice>' for i, o in enumerate(options)
    )
    return (
        f"<problem><multiplechoiceresponse><label>{prompt}</label>"
        f'<choicegroup type="MultipleChoice">{opts}</choicegroup></multiplechoiceresponse></problem>'
    )

def html(title, paragraphs, points=()):
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    if points:
        body += "<ul>" + "".join(f"<li>{p}</li>" for p in points) + "</ul>"
    return f"<h3>{title}</h3>{body}"

COURSES = {
    "course-v1:UNIA+CS101+2026": {
        "display_name": "Introduction to Computing",
        "display_organization": "University A",
        "display_coursenumber": "CS101",
        "short_description": "Foundations of computing for first-year BSc Computer Science students: how computers "
                             "represent information, how algorithms solve problems and how programs are written.",
        "overview": (
            "<section class=\"about\"><h2>About this course</h2><p>Introduction to Computing is the first module of "
            "University A's BSc Computer Science, delivered fully online through EduLage. You will learn how "
            "computers represent and process information, how to reason about algorithms, and how to write your "
            "first programs in Python.</p></section>"
            "<section class=\"prerequisites\"><h2>Requirements</h2><p>No prior programming experience. Secondary-school "
            "mathematics is assumed.</p></section>"
            "<section class=\"course-staff\"><h2>Course staff</h2><article class=\"teacher\"><h3>Dr A. Okafor</h3>"
            "<p>Senior Lecturer in Computer Science, University A</p></article></section>"
        ),
        "image": "discipline-computing.jpg",
        "signatory": {"name": "Dr A. Okafor", "title": "Senior Lecturer, Department of Computer Science",
                      "organization": "University A"},
        "sections": [
            ("Week 1 · What is computing?", [
                ("1.1 Computers and information", [
                    ("Reading: How computers represent information", html(
                        "How computers represent information",
                        ["Every piece of data a computer handles — text, images, sound, numbers — is stored as "
                         "sequences of binary digits (bits).",
                         "Understanding this representation is the starting point for everything else in the module."],
                        ["A bit is a 0 or a 1; eight bits form a byte.",
                         "Text is encoded using standards such as ASCII and Unicode.",
                         "Images are grids of pixels, each described by numbers."])),
                    ("Check: binary basics", choice("How many distinct values can one byte represent?",
                                                    ["8", "16", "256", "1024"], 2)),
                ]),
                ("1.2 Hardware and software", [
                    ("Reading: Hardware and software", html(
                        "Hardware and software",
                        ["Hardware is the physical machine: processor, memory, storage and input/output devices.",
                         "Software is the set of instructions that tells the hardware what to do — from the operating "
                         "system to the apps you use daily."])),
                ]),
            ]),
            ("Week 2 · Algorithms and data", [
                ("2.1 Thinking in algorithms", [
                    ("Reading: What is an algorithm?", html(
                        "What is an algorithm?",
                        ["An algorithm is a precise, finite sequence of steps that solves a class of problems.",
                         "Good algorithms are correct, clear, and efficient in time and memory."],
                        ["Sequence, selection and iteration are the three building blocks.",
                         "We describe algorithms in pseudocode before writing code."])),
                    ("Check: algorithm properties", choice(
                        "Which property means an algorithm always finishes after a finite number of steps?",
                        ["Correctness", "Termination", "Efficiency", "Abstraction"], 1)),
                ]),
            ]),
            ("Week 3 · Programming basics", [
                ("3.1 Your first Python program", [
                    ("Reading: Variables, types and expressions", html(
                        "Variables, types and expressions",
                        ["Python stores values in named variables. Each value has a type — integer, float, string, "
                         "boolean — that determines what you can do with it.",
                         "Expressions combine values and operators to produce new values."])),
                    ("Check: Python types", choice("What is the type of the value 3.5 in Python?",
                                                   ["int", "str", "float", "bool"], 2)),
                ]),
            ]),
            ("Module assessment", [
                ("End-of-module test", [
                    ("Question 1", choice("Which of these is NOT one of the three algorithmic building blocks?",
                                          ["Sequence", "Selection", "Iteration", "Compilation"], 3)),
                    ("Question 2", choice("Unicode is a standard for encoding …",
                                          ["images", "text", "sound", "processors"], 1)),
                ]),
            ]),
        ],
    },
    "course-v1:UNIB+MGT101+2026": {
        "display_name": "Principles of Management",
        "display_organization": "University B",
        "display_coursenumber": "MGT101",
        "short_description": "The core functions of management — planning, organising, leading and controlling — "
                             "applied to organisations in emerging and developed economies.",
        "overview": (
            "<section class=\"about\"><h2>About this course</h2><p>Principles of Management opens University B's "
            "Professional Certificate in Management. It introduces the manager's role and the four classic "
            "functions of management, with cases drawn from public, private and non-profit organisations.</p>"
            "</section>"
            "<section class=\"prerequisites\"><h2>Requirements</h2><p>Open to working professionals; no prior business "
            "study required. Assessments are taken online with a proctored final at an Open Education Centre.</p>"
            "</section>"
            "<section class=\"course-staff\"><h2>Course staff</h2><article class=\"teacher\"><h3>Prof. L. Mensah</h3>"
            "<p>Professor of Management, University B Business School</p></article></section>"
        ),
        "image": "discipline-business.jpg",
        "signatory": {"name": "Prof. L. Mensah", "title": "Dean, University B Business School",
                      "organization": "University B"},
        "sections": [
            ("Unit 1 · The manager's role", [
                ("1.1 What managers do", [
                    ("Reading: Management defined", html(
                        "Management defined",
                        ["Management is the process of achieving organisational goals by working with and through "
                         "people and other resources.",
                         "Henri Fayol's four functions — planning, organising, leading and controlling — still "
                         "structure how the discipline is taught."],
                        ["Planning sets goals and decides how to reach them.",
                         "Organising arranges people and resources.",
                         "Leading motivates and directs.",
                         "Controlling monitors performance and corrects course."])),
                    ("Check: functions of management", choice(
                        "Which function is concerned with monitoring performance against goals?",
                        ["Planning", "Organising", "Leading", "Controlling"], 3)),
                ]),
            ]),
            ("Unit 2 · Planning and decision-making", [
                ("2.1 Strategic and operational planning", [
                    ("Reading: Levels of planning", html(
                        "Levels of planning",
                        ["Strategic plans set an organisation's long-term direction; tactical and operational plans "
                         "translate that direction into departmental and day-to-day action.",
                         "Effective plans are specific, measurable and owned by a named person."])),
                    ("Check: planning horizons", choice("A three-year plan for entering a new market is an example of …",
                                                        ["operational planning", "strategic planning",
                                                         "contingency staffing", "quality control"], 1)),
                ]),
            ]),
            ("Unit 3 · Leading people", [
                ("3.1 Motivation and leadership", [
                    ("Reading: Leadership styles", html(
                        "Leadership styles",
                        ["Leaders influence others toward shared goals. Styles range from directive to participative; "
                         "the effective manager adapts style to the people and the situation."])),
                    ("Check: leadership", choice("A manager who involves the team in decisions is using a … style.",
                                                 ["directive", "laissez-faire", "participative", "coercive"], 2)),
                ]),
            ]),
            ("Certificate assessment", [
                ("Final assessment", [
                    ("Question 1", choice("Which management function arranges people and resources?",
                                          ["Planning", "Organising", "Leading", "Controlling"], 1)),
                    ("Question 2", choice("Fayol is associated with …",
                                          ["scientific management", "the four functions of management",
                                           "the hierarchy of needs", "lean manufacturing"], 1)),
                ]),
            ]),
        ],
    },
}

START = datetime(2026, 9, 1, tzinfo=timezone.utc)
END = datetime(2027, 1, 31, tzinfo=timezone.utc)

User = get_user_model()
admin = User.objects.filter(is_superuser=True).order_by("id").first()
store = modulestore()


def upload_image(course_key, filename):
    path = IMAGE_DIR / filename
    if not path.exists():
        print("  image missing, skipped:", path)
        return None
    loc = StaticContent.compute_location(course_key, filename)
    contentstore().save(StaticContent(loc, filename, "image/jpeg", path.read_bytes()))
    return filename


def seed(course_id, spec):
    key = CourseKey.from_string(course_id)
    try:
        store.create_course(key.org, key.course, key.run, admin.id, fields={"display_name": spec["display_name"]})
        print("created", course_id)
    except DuplicateCourseError:
        print("exists", course_id)

    with store.bulk_operations(key):
        course = store.get_course(key)
        for child in list(course.get_children()):
            store.delete_item(child.location, admin.id)

        course.display_name = spec["display_name"]
        course.display_organization = spec["display_organization"]
        course.display_coursenumber = spec["display_coursenumber"]
        course.short_description = spec["short_description"]
        course.overview = spec["overview"]
        course.language = "en"
        course.start = START
        course.end = END
        course.enrollment_start = START
        course.self_paced = False
        course.invitation_only = True
        course.catalog_visibility = "about"
        course.cert_html_view_enabled = True
        course.certificates_display_behavior = "early_no_info"
        course.certificate_available_date = None
        course.learning_info = ["How to reason about problems in the discipline",
                                "Core vocabulary and models used by practitioners",
                                "How assessed work is recognised on your EduLage credential record"]
        course.instructor_info = {"instructors": [{"name": spec["signatory"]["name"],
                                                   "title": spec["signatory"]["title"],
                                                   "organization": spec["signatory"]["organization"],
                                                   "image": "", "bio": ""}]}
        course.grading_policy = {
            "GRADER": [
                {"type": "Check", "short_label": "Check", "min_count": 1, "drop_count": 0, "weight": 0.4},
                {"type": "Final", "short_label": "Final", "min_count": 1, "drop_count": 0, "weight": 0.6},
            ],
            "GRADE_CUTOFFS": {"Pass": 0.5},
        }
        course.certificates = {"certificates": [{
            "id": 1, "name": "Certificate", "description": "", "is_active": True, "version": 1, "course_title": "",
            "signatories": [{"id": 1, "signature_image_path": "", **spec["signatory"]}],
        }]}
        image = upload_image(key, spec["image"])
        if image:
            course.course_image = image
        store.update_item(course, admin.id)

        for s_index, (section_title, subsections) in enumerate(spec["sections"]):
            chapter = store.create_child(admin.id, course.location, "chapter", fields={"display_name": section_title})
            is_final = s_index == len(spec["sections"]) - 1
            for sub_title, units in subsections:
                sequential = store.create_child(admin.id, chapter.location, "sequential", fields={
                    "display_name": sub_title, "graded": True, "format": "Final" if is_final else "Check",
                })
                for unit_title, content in units:
                    vertical = store.create_child(admin.id, sequential.location, "vertical",
                                                  fields={"display_name": unit_title})
                    block_type = "problem" if content.startswith("<problem>") else "html"
                    fields = {"display_name": unit_title, "data": content}
                    if block_type == "problem":
                        fields.update({"max_attempts": 3, "showanswer": "finished", "weight": 1.0})
                    store.create_child(admin.id, vertical.location, block_type, fields=fields)

    store.publish(key.make_usage_key("course", "course"), admin.id)
    print("  seeded", len(spec["sections"]), "sections; published")


for cid, cspec in COURSES.items():
    seed(cid, cspec)
