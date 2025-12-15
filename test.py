# Add these new imports at top
from flask import Blueprint, render_template, abort, request, redirect, url_for, flash, session, jsonify
import sqlite3
import os

test_bp = Blueprint('test_bp', __name__, template_folder='templates')
DATABASE = os.environ.get('TEST_DB_FILE', 'test_database.db')

def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

# Keep existing list_tests() and view_test_questions() unchanged

@test_bp.route('/tests/<int:test_id>/start')
def start_test(test_id):
    session[f'test_{test_id}_answers'] = {}
    session[f'test_{test_id}_marked'] = []
    session[f'test_{test_id}_skipped'] = []
    return redirect(url_for('test_bp.single_question', test_id=test_id, q_num=1))

# Keep existing single_question(), toggle_mark_ajax() unchanged

@test_bp.route('/tests/<int:test_id>/submit', methods=['GET', 'POST'])
def submit_test(test_id):
    if request.method == 'POST' and request.form.get('review') == 'review':
        return redirect(url_for('test_bp.review_attempted', test_id=test_id))
    
    conn = get_connection()
    try:
        questions = conn.execute(
            '''SELECT id, correct_answer FROM test_questions WHERE test_id = ? ORDER BY id''',
            (test_id,)
        ).fetchall()
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
        
        # Save user responses to database
        user_id = session.get('user_id')  # Assuming user session exists
        answers = session.get(f'test_{test_id}_answers', {})
        
        for q in questions:
            qid = q['id']
            user_answer = answers.get(str(qid))
            is_correct = 1 if user_answer == q['correct_answer'] else 0
            
            conn.execute('''
                INSERT INTO user_responses (test_id, user_id, question_id, user_answer, is_correct)
                VALUES (?, ?, ?, ?, ?)
            ''', (test_id, user_id, qid, user_answer, is_correct))
        
        conn.commit()
        
        # Calculate scores
        total = len(questions)
        correct = len([q for q in questions if answers.get(str(q['id'])) == q['correct_answer']])
        wrong = len([q for q in questions if answers.get(str(q['id'])) != q['correct_answer'] and answers.get(str(q['id']))])
        unanswered = total - correct - wrong
        
    finally:
        conn.close()

    # Clear session
    for key in [f'test_{test_id}_answers', f'test_{test_id}_marked', f'test_{test_id}_skipped']:
        session.pop(key, None)

    return render_template('test/report.html',
                           test=test,
                           total=total,
                           correct=correct,
                           wrong=wrong,
                           unanswered=unanswered)

@test_bp.route('/tests/<int:test_id>/review')
def review_attempted(test_id):
    conn = get_connection()
    try:
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
        questions = conn.execute('''
            SELECT tq.*, ur.user_answer, ur.is_correct
            FROM test_questions tq
            LEFT JOIN user_responses ur ON tq.id = ur.question_id 
            WHERE tq.test_id = ? AND ur.test_id = ?
            ORDER BY tq.id
        ''', (test_id, test_id)).fetchall()
    finally:
        conn.close()
    
    correct_questions = [q for q in questions if q['is_correct'] == 1]
    incorrect_questions = [q for q in questions if q['is_correct'] == 0]
    
    return render_template('test/review_attempted.html',
                           test=test,
                           all_questions=questions,
                           correct_questions=correct_questions,
                           incorrect_questions=incorrect_questions)

@test_bp.route('/tests/<int:test_id>/review/<filter_type>/<int:q_index>')
def review_question(test_id, filter_type, q_index):
    conn = get_connection()
    try:
        test = conn.execute('SELECT * FROM test_info WHERE id = ?', (test_id,)).fetchone()
        
        if filter_type == 'correct':
            questions = conn.execute('''
                SELECT tq.*, ur.user_answer, ur.is_correct
                FROM test_questions tq
                JOIN user_responses ur ON tq.id = ur.question_id 
                WHERE tq.test_id = ? AND ur.test_id = ? AND ur.is_correct = 1
                ORDER BY tq.id
            ''', (test_id, test_id)).fetchall()
        else:  # incorrect
            questions = conn.execute('''
                SELECT tq.*, ur.user_answer, ur.is_correct
                FROM test_questions tq
                JOIN user_responses ur ON tq.id = ur.question_id 
                WHERE tq.test_id = ? AND ur.test_id = ? AND ur.is_correct = 0
                ORDER BY tq.id
            ''', (test_id, test_id)).fetchall()
        
        if q_index < 1 or q_index > len(questions):
            abort(404)
            
        question = questions[q_index - 1]
        prev_q = q_index - 1 if q_index > 1 else None
        next_q = q_index + 1 if q_index < len(questions) else None
        
    finally:
        conn.close()
    
    return render_template('test/review_question.html',
                           test=test,
                           question=question,
                           q_index=q_index,
                           total=len(questions),
                           prev_q=prev_q,
                           next_q=next_q,
                           filter_type=filter_type)
