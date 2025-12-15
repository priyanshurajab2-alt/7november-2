from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os


test_bp = Blueprint('test_bp', __name__, template_folder='templates')
DATABASE = os.environ.get('TEST_DB_FILE', 'test_database.db')


def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


@test_bp.route('/tests')
def list_tests():
    conn = get_connection()
    try:
        cur = conn.execute('''
            SELECT id, test_name, description, duration_minutes, start_time, end_time
            FROM test_info
            ORDER BY created_at DESC
        ''')
        tests = cur.fetchall()
    finally:
        conn.close()
    return render_template('test/tests.html', tests=tests)


@test_bp.route('/tests/<int:test_id>/questions')
def view_test_questions(test_id):
    conn = get_connection()
    try:
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
        if not test:
            abort(404, description="Test not found")

        questions = conn.execute('''
            SELECT subject, topic, question, option_a, option_b, option_c, option_d, correct_answer
            FROM test_questions
            WHERE test_id = ?
            ORDER BY subject, topic, id
        ''', (test_id,)).fetchall()

    finally:
        conn.close()

    grouped_questions = {}
    for q in questions:
        grouped_questions.setdefault(q['subject'], {})
        grouped_questions[q['subject']].setdefault(q['topic'], [])
        grouped_questions[q['subject']][q['topic']].append(q)

    return render_template('test/test_questions.html', test=test, grouped_questions=grouped_questions)


# -----------------------------
# Single-question-per-page with independent AJAX marking and skip support
# -----------------------------


@test_bp.route('/tests/<int:test_id>/start')
def start_test(test_id):
    session[f'test_{test_id}_answers'] = {}
    session[f'test_{test_id}_marked'] = []
    session[f'test_{test_id}_skipped'] = []
    return redirect(url_for('test_bp.single_question', test_id=test_id, q_num=1))


@test_bp.route('/tests/<int:test_id>/question/<int:q_num>', methods=['GET', 'POST'])
def single_question(test_id, q_num):
    conn = get_connection()
    try:
        questions = conn.execute(
            '''SELECT id, subject, topic, question, option_a, option_b, option_c, option_d, correct_answer
               FROM test_questions WHERE test_id = ? ORDER BY id''',
            (test_id,)
        ).fetchall()
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
    finally:
        conn.close()

    if not test or not questions or q_num < 1 or q_num > len(questions):
        abort(404)

    question = questions[q_num - 1]

    answer_key = f'test_{test_id}_answers'
    mark_key = f'test_{test_id}_marked'
    skip_key = f'test_{test_id}_skipped'

    if answer_key not in session:
        session[answer_key] = {}
    if mark_key not in session:
        session[mark_key] = []
    if skip_key not in session:
        session[skip_key] = []

    answers = session[answer_key]
    marked = set(session[mark_key])
    skipped = set(session[skip_key])

    if request.method == 'POST':
        selected_option = request.form.get('answer')
        nav = request.form.get('nav')  # previous, next, submit, skip

        if nav == 'skip':
            # Mark the question as skipped
            skipped.add(str(question['id']))
            session[skip_key] = list(skipped)
            # Remove answer if it exists, since it's skipped
            if str(question['id']) in answers:
                del answers[str(question['id'])]
                session[answer_key] = answers
            # Navigate forward if possible
            next_q_num = q_num + 1 if q_num < len(questions) else q_num
            return redirect(url_for('test_bp.single_question', test_id=test_id, q_num=next_q_num))

        if nav in ('next', 'submit'):
            if not selected_option:
                flash("Please select an option or choose Skip.")
                return render_template(
                    'test/single_question.html',
                    test=test,
                    question=question,
                    q_num=q_num,
                    total=len(questions),
                    selected_answer=answers.get(str(question['id']), None),
                    marked_questions=marked,
                    skipped_questions=skipped,
                    duration_minutes=test['duration_minutes']
                )
            # Save answer and remove from skipped if any
            answers[str(question['id'])] = selected_option
            session[answer_key] = answers
            if str(question['id']) in skipped:
                skipped.remove(str(question['id']))
                session[skip_key] = list(skipped)

        elif nav == 'previous':
            # Save answer if selected before going back
            if selected_option:
                answers[str(question['id'])] = selected_option
                session[answer_key] = answers

        # Navigate accordingly
        if nav == 'previous':
            prev_q_num = max(1, q_num - 1)
            return redirect(url_for('test_bp.single_question', test_id=test_id, q_num=prev_q_num))
        elif nav == 'next':
            next_q_num = min(len(questions), q_num + 1)
            return redirect(url_for('test_bp.single_question', test_id=test_id, q_num=next_q_num))
        elif nav == 'submit':
            return redirect(url_for('test_bp.submit_test', test_id=test_id))

    return render_template(
        'test/single_question.html',
        test=test,
        question=question,
        q_num=q_num,
        total=len(questions),
        selected_answer=answers.get(str(question['id']), None),
        marked_questions=marked,
        skipped_questions=skipped,
        duration_minutes=test['duration_minutes']
    )


# AJAX toggle mark
@test_bp.route('/tests/<int:test_id>/question/<int:q_num>/toggle_mark', methods=['POST'])
def toggle_mark_ajax(test_id, q_num):
    conn = get_connection()
    try:
        questions = conn.execute('SELECT id FROM test_questions WHERE test_id = ? ORDER BY id', (test_id,)).fetchall()
    finally:
        conn.close()

    if not questions or q_num < 1 or q_num > len(questions):
        return jsonify({'success': False, 'error': 'Invalid question'}), 400

    q_id_str = str(questions[q_num - 1]['id'])

    mark_key = f'test_{test_id}_marked'
    if mark_key not in session:
        session[mark_key] = []
    marked = set(session[mark_key])

    if q_id_str in marked:
        marked.remove(q_id_str)
        marked_now = False
    else:
        marked.add(q_id_str)
        marked_now = True

    session[mark_key] = list(marked)

    return jsonify({'success': True, 'marked': marked_now})


@test_bp.route('/tests/<int:test_id>/review')
def review_test(test_id):
    conn = get_connection()
    try:
        questions = conn.execute('''SELECT id FROM test_questions WHERE test_id = ? ORDER BY id''', (test_id,)).fetchall()
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
    finally:
        conn.close()
    if not test or not questions:
        abort(404)

    answer_key = f'test_{test_id}_answers'
    mark_key = f'test_{test_id}_marked'
    skip_key = f'test_{test_id}_skipped'

    answers = session.get(answer_key, {})
    marked = set(session.get(mark_key, []))
    skipped = set(session.get(skip_key, []))

    return render_template('test/review.html',
                           test=test,
                           questions=questions,
                           answers=answers,
                           marked=marked,
                           skipped=skipped)


@test_bp.route('/tests/<int:test_id>/submit', methods=['GET'])
def submit_test(test_id):
    conn = get_connection()
    try:
        questions = conn.execute(
            '''SELECT id, correct_answer FROM test_questions WHERE test_id = ? ORDER BY id''',
            (test_id,)
        ).fetchall()
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
    finally:
        conn.close()

    answer_key = f'test_{test_id}_answers'
    mark_key = f'test_{test_id}_marked'
    skip_key = f'test_{test_id}_skipped'

    answers = session.get(answer_key, {})
    marked = set(session.get(mark_key, []))
    skipped = set(session.get(skip_key, []))

    total = len(questions)
    correct = 0
    wrong = 0
    unanswered = 0

    for q in questions:
        qid = str(q['id'])
        ans = answers.get(qid)
        if ans is None:
            if qid in skipped:
                # Count skipped as unanswered for scoring
                unanswered += 1
            else:
                unanswered += 1
        elif ans == q['correct_answer']:
            correct += 1
        else:
            wrong += 1

    # Clear session keys to avoid confusion on retake (optional)
    session.pop(answer_key, None)
    session.pop(mark_key, None)
    session.pop(skip_key, None)

    return render_template('test/report.html',
                           test=test,
                           total=total,
                           correct=correct,
                           wrong=wrong,
                           unanswered=unanswered,
                           marked=marked,
                           skipped=skipped)
