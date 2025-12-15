from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os
from dynamic_db_handler import dynamic_db_handler  # Import your dynamic DB handler

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
            SELECT id, subject, topic, question, option_a, option_b, option_c, option_d, correct_answer, explanation
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

# Single-question-per-page with independent AJAX marking and skip support
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
        nav = request.form.get('nav')

        if nav == 'skip':
            skipped.add(str(question['id']))
            session[skip_key] = list(skipped)
            if str(question['id']) in answers:
                del answers[str(question['id'])]
                session[answer_key] = answers
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
            answers[str(question['id'])] = selected_option
            session[answer_key] = answers
            if str(question['id']) in skipped:
                skipped.remove(str(question['id']))
                session[skip_key] = list(skipped)

        elif nav == 'previous':
            if selected_option:
                answers[str(question['id'])] = selected_option
                session[answer_key] = answers

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

# NEW: Save user response to user_response database
@test_bp.route('/tests/<int:test_id>/submit', methods=['GET', 'POST'])
def submit_test(test_id):
    # Save to user_response database first
    if request.method == 'POST':
        save_user_response(test_id)
    
    conn = get_connection()
    try:
        questions = conn.execute(
            '''SELECT id, correct_answer, explanation FROM test_questions WHERE test_id = ? ORDER BY id''',
            (test_id,)
        ).fetchall()
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
    finally:
        conn.close()

    answer_key = f'test_{test_id}_answers'
    answers = session.get(answer_key, {})

    total = len(questions)
    correct = 0
    wrong = 0
    unanswered = 0

    for q in questions:
        qid = str(q['id'])
        ans = answers.get(qid)
        if ans is None:
            unanswered += 1
        elif ans == q['correct_answer']:
            correct += 1
        else:
            wrong += 1

    # Clear session
    session.pop(answer_key, None)
    session.pop(f'test_{test_id}_marked', None)
    session.pop(f'test_{test_id}_skipped', None)

    return render_template('test/report.html',
                           test=test,
                           total=total,
                           correct=correct,
                           wrong=wrong,
                           unanswered=unanswered)

def save_user_response(test_id):
    """Save user test response to user_response database"""
    try:
        # Connect to user_response.db (create if doesn't exist)
        user_db = 'user_response.db'
        user_conn = sqlite3.connect(user_db)
        user_conn.row_factory = sqlite3.Row
        
        # Create tables if not exists
        user_conn.execute('''
            CREATE TABLE IF NOT EXISTS user_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id INTEGER NOT NULL,
                user_id TEXT,
                question_id INTEGER,
                user_answer TEXT,
                correct_answer TEXT,
                is_correct INTEGER,
                explanation TEXT,
                taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        test_conn = get_connection()
        questions = test_conn.execute(
            'SELECT id, correct_answer, explanation FROM test_questions WHERE test_id = ? ORDER BY id',
            (test_id,)
        ).fetchall()
        test_conn.close()
        
        answer_key = f'test_{test_id}_answers'
        answers = session.get(answer_key, {})
        user_id = session.get('user_id', 'anonymous')
        
        for q in questions:
            user_answer = answers.get(str(q['id']), None)
            is_correct = 1 if user_answer == q['correct_answer'] else 0
            
            user_conn.execute('''
                INSERT INTO user_responses 
                (test_id, user_id, question_id, user_answer, correct_answer, is_correct, explanation)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (test_id, user_id, q['id'], user_answer, q['correct_answer'], is_correct, q['explanation']))
        
        user_conn.commit()
        user_conn.close()
        
    except Exception as e:
        flash(f"Error saving response: {str(e)}", "error")

# NEW: Review attempted test with filters
@test_bp.route('/tests/<int:test_id>/review_attempted')
def review_attempted(test_id):
    user_id = session.get('user_id', 'anonymous')
    
    # Get user's responses from user_response.db
    user_db = 'user_response.db'
    user_conn = sqlite3.connect(user_db)
    user_conn.row_factory = sqlite3.Row
    
    filter_type = request.args.get('filter', 'all')  # 'correct', 'incorrect', 'all'
    
    query = '''
        SELECT ur.*, tq.question, tq.option_a, tq.option_b, tq.option_c, tq.option_d, tq.subject, tq.topic
        FROM user_responses ur
        JOIN test_questions tq ON ur.question_id = tq.id
        WHERE ur.test_id = ? AND ur.user_id = ?
    '''
    params = [test_id, user_id]
    
    if filter_type == 'correct':
        query += ' AND ur.is_correct = 1'
    elif filter_type == 'incorrect':
        query += ' AND ur.is_correct = 0'
    
    query += ' ORDER BY ur.id'
    
    responses = user_conn.execute(query, params).fetchall()
    user_conn.close()
    
    # Group by correctness for filter counts
    correct_count = len([r for r in responses if r['is_correct']])
    incorrect_count = len(responses) - correct_count
    
    test_conn = get_connection()
    test = test_conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
    test_conn.close()
    
    return render_template('test/review_attempted.html',
                          test=test,
                          responses=responses,
                          filter_type=filter_type,
                          correct_count=correct_count,
                          incorrect_count=incorrect_count)

# NEW: Review specific question with explanation
@test_bp.route('/tests/<int:test_id>/review_question/<int:response_id>')
def review_question(test_id, response_id):
    user_id = session.get('user_id', 'anonymous')
    
    # Get response details
    user_db = 'user_response.db'
    user_conn = sqlite3.connect(user_db)
    user_conn.row_factory = sqlite3.Row
    
    response = user_conn.execute('''
        SELECT ur.*, tq.question, tq.option_a, tq.option_b, tq.option_c, tq.option_d, tq.subject, tq.topic
        FROM user_responses ur
        JOIN test_questions tq ON ur.question_id = tq.id
        WHERE ur.id = ? AND ur.test_id = ? AND ur.user_id = ?
    ''', (response_id, test_id, user_id)).fetchone()
    
    if not response:
        abort(404)
    
    # Get previous/next in same filter group
    filter_type = request.args.get('filter', 'all')
    prev_next_query = '''
        SELECT id FROM user_responses 
        WHERE test_id = ? AND user_id = ? AND is_correct = ?
        ORDER BY id
    '''
    params = [test_id, user_id, response['is_correct']]
    
    if filter_type == 'all':
        prev_next_query = prev_next_query.replace('is_correct = ?', '1=1')
        params = params[:-1]
    
    all_same_group = user_conn.execute(prev_next_query, params).fetchall()
    
    current_index = next((i for i, r in enumerate(all_same_group) if r['id'] == response_id), -1)
    prev_id = all_same_group[current_index - 1]['id'] if current_index > 0 else None
    next_id = all_same_group[current_index + 1]['id'] if current_index < len(all_same_group) - 1 else None
    
    user_conn.close()
    
    return render_template('test/review_question.html',
                          response=response,
                          prev_response_id=prev_id,
                          next_response_id=next_id,
                          test_id=test_id,
                          filter=request.args.get('filter', 'all'))
