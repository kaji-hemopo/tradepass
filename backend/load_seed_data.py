"""
TradePass — Seed Data Loader
Loads research/seed_questions.json into the local SQLite database.
Run once: python load_seed_data.py
"""
import json
import uuid
from pathlib import Path

from database import get_connection, init_db

SEED_FILE = Path(__file__).parent.parent / "research" / "seed_questions.json"
TOPIC_MAP = {
    "Voltage Drop":                   "voltage-drop",
    "Fault Loop Impedance":           "fault-loop-zs",
    "AS/NZS 3000 Application":        "as-nzs-3000",
    "AS/NZS 3000 Wiring Rules":       "as-nzs-3000",
    "Insulation Resistance":          "insulation-resistance",
    "Max Demand & Diversity":          "max-demand",
    "Maximum Demand":                 "max-demand",
    "RCD & MCB Protection":          "rcd-mcb",
    "Protection & Discrimination":     "rcd-mcb",
    "Supply Systems":                 "supply-systems",
    "Motor Starters":                "motor-starters",
    "Motors & Motor Starters":       "motor-starters",
    "Switchboards":                   "switchboards",
    "Circuit Design":                 "circuit-design",
    "Testing & Verification":         "testing-verification",
}

WEIGHT_MAP = {
    "voltage-drop":       5,
    "fault-loop-zs":      5,
    "as-nzs-3000":         5,
    "insulation-resistance": 3,
    "max-demand":         3,
    "rcd-mcb":            3,
    "supply-systems":     2,
    "motor-starters":     2,
    "switchboards":       2,
    "circuit-design":     2,
    "testing-verification": 3,
}

DESCRIPTION_MAP = {
    "voltage-drop":          "AS/NZS 3000 volt drop calculations and limits",
    "fault-loop-zs":         "Zs verification, Ze calculation, Zt timing",
    "as-nzs-3000":           "General wiring rules, cable sizing, installation methods",
    "insulation-resistance": "IR testing, min values, test voltages",
    "max-demand":           "Diversity factors, demand calculations, cable selection",
    "rcd-mcb":              "RCD sizing, MCB curves, discrimination",
    "supply-systems":       "TT/TN/CS earthing arrangements",
    "motor-starters":      "DOL, star-delta, soft starters, thermal overload",
    "switchboards":        "Board design, clearances, segregation, labelling",
    "circuit-design":      "Circuit types, protective devices, documentation",
    "testing-verification": "Verification testing sequence per AS/NZS 3000",
}

def load() -> int:
    init_db()
    conn = get_connection()
    cur = conn.cursor()

    # Load seed questions JSON
    data = json.loads(SEED_FILE.read_text())
    questions = data["questions"]

    # Build topic slug → id map (ensure all topics exist)
    topic_ids = {}
    for q in questions:
        topic_name = q["topic"]
        slug = TOPIC_MAP.get(topic_name, topic_name.lower().replace(" ", "-"))
        if slug not in topic_ids:
            cur.execute(
                """
                INSERT OR IGNORE INTO topics (name, slug, description, weight)
                VALUES (?, ?, ?, ?)
                """,
                (topic_name, slug, DESCRIPTION_MAP.get(slug, ""), WEIGHT_MAP.get(slug, 2)),
            )
            cur.execute("SELECT id FROM topics WHERE slug = ?", (slug,))
            topic_ids[slug] = cur.fetchone()["id"]

    conn.commit()

    # Load questions
    loaded = 0
    for q in questions:
        topic_name = q["topic"]
        slug = TOPIC_MAP.get(topic_name, topic_name.lower().replace(" ", "-"))
        topic_id = topic_ids[slug]
        qid = q["id"] if "id" in q else str(uuid.uuid4())

        options = q["options"]
        correct_idx = q["correct_answer"]

        # Build answer_text as the correct option string
        answer_text = options[correct_idx]
        explanation = q.get("explanation", "")
        reference = q.get("reference", "")

        # Merge all options into question_text for display purposes
        question_text = q["question"]
        option_text = "\n".join(
            f"{'✓ ' if i == correct_idx else chr(65+i) + '. '}{opt}"
            for i, opt in enumerate(options)
        )

        options_json = json.dumps(options)
        cur.execute(
            """
            INSERT OR REPLACE INTO questions
                (id, topic_id, question_text, answer_text, explanation,
                 reference_clause, difficulty, is_active, correct_answer_index,
                 options)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                qid,
                topic_id,
                question_text,
                answer_text,
                explanation,
                reference,
                q.get("difficulty", "medium"),
                correct_idx,
                options_json,
            ),
        )
        loaded += 1

    conn.commit()
    conn.close()
    return loaded


if __name__ == "__main__":
    import sys
    n = load()
    print(f"Loaded {n} questions into tradepass.db")
    if "--demo" in sys.argv:
        from seed_demo_user import seed_demo_user
        seed_demo_user()
