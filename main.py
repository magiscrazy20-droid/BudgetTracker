import sqlite3
from flask import Flask, render_template, request, redirect, url_for, flash, session
from datetime import datetime
from calendar import monthrange
import functools
import os

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_demo')
DB_NAME = os.environ.get('DB_PATH', 'budget_tracker.db')

def reset_db():
    try:
        if os.path.exists(DB_NAME):
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            os.rename(DB_NAME, f'{DB_NAME}.corrupt_{ts}')
        init_db()
    except Exception:
        pass

def get_db_connection():
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute('PRAGMA integrity_check')
            row = cur.fetchone()
            if not row or row[0] != 'ok':
                raise sqlite3.DatabaseError('integrity failed')
        except sqlite3.DatabaseError:
            conn.close()
            reset_db()
            conn = sqlite3.connect(DB_NAME)
            conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.DatabaseError:
        reset_db()
        conn = sqlite3.connect(DB_NAME)
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_db_connection()
    with conn:
        # Create expenses table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT,
                amount REAL NOT NULL,
                user_id TEXT
            )
        ''')
        # Check if user_id column exists in expenses, if not add it
        try:
            conn.execute('SELECT user_id FROM expenses LIMIT 1')
        except sqlite3.OperationalError:
            conn.execute('ALTER TABLE expenses ADD COLUMN user_id TEXT')

        # Create budget table
        conn.execute('''
            CREATE TABLE IF NOT EXISTS budget (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_limit REAL NOT NULL,
                user_id TEXT UNIQUE
            )
        ''')
        # Check if user_id column exists in budget, if not add it
        try:
            conn.execute('SELECT user_id FROM budget LIMIT 1')
        except sqlite3.OperationalError:
            conn.execute('ALTER TABLE budget ADD COLUMN user_id TEXT')
            # Add unique index if possible or rely on app logic for legacy
    conn.close()

def login_required(view):
    @functools.wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

@app.context_processor
def inject_user():
    return dict(current_user=session.get('user_id'))

@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username'].strip()
        if username:
            session['user_id'] = username
            conn = get_db_connection()
            # Ensure user has a budget entry
            existing_budget = conn.execute('SELECT * FROM budget WHERE user_id = ?', (username,)).fetchone()
            if not existing_budget:
                conn.execute('INSERT INTO budget (daily_limit, user_id) VALUES (?, ?)', (100.0, username))
                conn.commit()
            conn.close()
            return redirect(url_for('index'))
        else:
            flash('Please enter a name')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    user_id = session['user_id']
    conn = get_db_connection()
    
    # Get today's date string
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    # Get daily budget for user
    budget_row = conn.execute('SELECT daily_limit FROM budget WHERE user_id = ?', (user_id,)).fetchone()
    daily_limit = budget_row['daily_limit'] if budget_row else 100.0
    
    # Get today's total expenses for user
    total_today_row = conn.execute('SELECT SUM(amount) as total FROM expenses WHERE date = ? AND user_id = ?', (today_str, user_id)).fetchone()
    total_today = total_today_row['total'] if total_today_row['total'] else 0.0
    
    # Get recent expenses for user
    expenses = conn.execute('SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC, id DESC LIMIT 20', (user_id,)).fetchall()
    
    conn.close()
    
    remaining = daily_limit - total_today
    
    return render_template('index.html', 
                           expenses=expenses, 
                           daily_limit=daily_limit, 
                           total_today=total_today,
                           remaining=remaining,
                           today=today_str)

@app.route('/add', methods=('GET', 'POST'))
@login_required
def add_expense():
    user_id = session['user_id']
    if request.method == 'POST':
        date = request.form['date']
        category = request.form['category']
        description = request.form['description']
        amount_raw = request.form['amount']

        if not date or not amount_raw:
            flash('Date and Amount are required!')
        else:
            try:
                amount = float(amount_raw)
            except ValueError:
                flash('Amount must be a number')
                return render_template('add.html', today=datetime.now().strftime('%Y-%m-%d'))
            conn = get_db_connection()
            conn.execute('INSERT INTO expenses (date, category, description, amount, user_id) VALUES (?, ?, ?, ?, ?)',
                         (date, category, description, amount, user_id))
            conn.commit()
            conn.close()
            return redirect(url_for('index'))

    return render_template('add.html', today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/delete/<int:id>', methods=('POST',))
@login_required
def delete_expense(id):
    user_id = session['user_id']
    conn = get_db_connection()
    conn.execute('DELETE FROM expenses WHERE id = ? AND user_id = ?', (id, user_id))
    conn.commit()
    conn.close()
    flash('Expense deleted!')
    return redirect(url_for('index'))

@app.route('/set_budget', methods=('POST',))
@login_required
def set_budget():
    user_id = session['user_id']
    new_limit = request.form['daily_limit']
    if new_limit:
        conn = get_db_connection()
        # Update specific user's budget
        conn.execute('UPDATE budget SET daily_limit = ? WHERE user_id = ?', (new_limit, user_id))
        conn.commit()
        conn.close()
        flash('Daily budget updated!')
    return redirect(url_for('index'))

@app.route('/monthly', strict_slashes=False)
@login_required
def monthly():
    user_id = session['user_id']
    now = datetime.now()
    ym = request.args.get('ym')
    if ym:
        try:
            y, m = ym.split('-')
            year = int(y)
            month = int(m)
        except:
            year = now.year
            month = now.month
    else:
        y = request.args.get('year')
        m = request.args.get('month')
        year = int(y) if y and y.isdigit() else now.year
        month = int(m) if m and m.isdigit() else now.month
    first_day = datetime(year, month, 1)
    last_day_num = monthrange(year, month)[1]
    last_day = datetime(year, month, last_day_num)
    date_from = first_day.strftime('%Y-%m-%d')
    is_current_month = (year == now.year and month == now.month)
    limit_day = now.day if is_current_month else last_day_num
    date_to = (datetime(year, month, limit_day)).strftime('%Y-%m-%d')
    conn = get_db_connection()
    daily_rows = conn.execute(
        'SELECT date, SUM(amount) as total FROM expenses WHERE user_id = ? AND date BETWEEN ? AND ? GROUP BY date ORDER BY date',
        (user_id, date_from, date_to)
    ).fetchall()
    expense_rows = conn.execute(
        'SELECT * FROM expenses WHERE user_id = ? AND date BETWEEN ? AND ? ORDER BY date ASC, id DESC',
        (user_id, date_from, date_to)
    ).fetchall()

    conn.close()
    daily_map = {row['date']: row['total'] if row['total'] else 0.0 for row in daily_rows}
    days = []
    for d in range(1, limit_day + 1):
        ds = datetime(year, month, d).strftime('%Y-%m-%d')
        days.append({'day': d, 'date': ds, 'total': daily_map.get(ds, 0.0)})
    grouped = {}
    for e in expense_rows:
        grouped.setdefault(e['date'], []).append(e)
    grouped_list = []
    for k, v in sorted(grouped.items()):
        total = sum(float(item['amount']) for item in v)
        grouped_list.append({'date': k, 'items': v, 'total': total})
    month_label = first_day.strftime('%B %Y')
    monthly_total = sum(d['total'] for d in days)
    prev_year = year - 1 if month == 1 else year
    prev_month = 12 if month == 1 else month - 1
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    return render_template(
        'monthly.html',
        days=days,
        grouped_expenses=grouped_list,
        year=year,
        month=month,
        month_label=month_label,
        monthly_total=monthly_total,
        prev_year=prev_year,
        prev_month=prev_month,
        next_year=next_year,
        next_month=next_month
    )

if __name__ == '__main__':
    try:
        init_db()
    except sqlite3.DatabaseError:
        try:
            if os.path.exists(DB_NAME):
                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                os.rename(DB_NAME, f'{DB_NAME}.corrupt_{ts}')
            init_db()
        except Exception:
            pass
    app.run(debug=True)
