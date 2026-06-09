import os
import re
from dotenv import load_dotenv
load_dotenv()

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from flask_mail import Mail, Message as MailMessage
from smart_parser import parse_smart_input

app = Flask(__name__)
app.secret_key = 'hello_world'

app.config["MONGO_URI"] = "mongodb+srv://atharvakantode16:todoproject162004@to-do-cluster.whftpzh.mongodb.net/tododb?retryWrites=true&w=majority&appName=to-do-cluster"
mongo = PyMongo(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.init_app(app)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

mail = Mail(app)

IST = timezone(timedelta(hours=5, minutes=30))

PRIORITIES = ['low', 'medium', 'high']
CATEGORIES = ['General', 'Work', 'Personal', 'Study', 'Health', 'Finance', 'Shopping', 'Other']

@app.template_filter('to_local')
def to_local_filter(utc_dt):
    if utc_dt is None:
        return None
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(IST)

@app.context_processor
def inject_globals():
    return {
        'priorities': PRIORITIES,
        'categories': CATEGORIES,
        'now_utc': datetime.now(timezone.utc)
    }

# Helper to make any datetime timezone-aware (UTC)
def ensure_aware(dt):
    """Ensure a datetime is timezone-aware (UTC). Returns None if input is None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

# --- User Model --- #
class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

# --- Register --- #
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']

        if not username or len(username) < 3:
            flash('Username must be at least 3 characters.', 'danger')
            return redirect(url_for('register'))
        if not password or len(password) < 4:
            flash('Password must be at least 4 characters.', 'danger')
            return redirect(url_for('register'))

        if mongo.db.users.find_one({'username': username}):
            flash('Username already exists!', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password)
        mongo.db.users.insert_one({'username': username, 'password': hashed_password})
        flash('Registered successfully! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# --- Login --- #
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user_data = mongo.db.users.find_one({'username': username})
        if user_data and check_password_hash(user_data['password'], password):
            user = User(user_data)
            login_user(user)
            flash('Logged in successfully.', 'success')
            return redirect(url_for('index'))
        else:
            flash('Invalid credentials.', 'danger')
            return redirect(url_for('login'))

    return render_template('login.html')

@login_manager.unauthorized_handler
def unauthorized_callback():
    return redirect(url_for('login'))

# --- Logout --- #
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('landing'))

# --- Landing Page --- #
@app.route('/landing')
def landing():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    return render_template('landing.html')

# --- Home / To-Do Page --- #
@app.route('/', methods=['GET', 'POST'])
def index():
    if not current_user.is_authenticated:
        return render_template('landing.html')

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        desc = request.form.get('desc', '').strip()
        reminder = request.form.get('reminder', '').strip()
        priority = request.form.get('priority', 'medium').lower()
        category = request.form.get('category', 'General')
        due_date_str = request.form.get('due_date', '').strip()

        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('index'))
        if not desc:
            flash('Description is required.', 'danger')
            return redirect(url_for('index'))

        if priority not in PRIORITIES:
            priority = 'medium'
        if category not in CATEGORIES:
            category = 'General'

        reminder_time = None
        if reminder:
            local_dt = datetime.fromisoformat(reminder)
            local_dt = local_dt.replace(tzinfo=IST)
            reminder_time = local_dt.astimezone(timezone.utc)

        due_date = None
        if due_date_str:
            local_dt = datetime.fromisoformat(due_date_str)
            local_dt = local_dt.replace(tzinfo=IST)
            due_date = local_dt.astimezone(timezone.utc)

        # Get max order for this user
        last = mongo.db.todos.find_one(
            {'user_id': ObjectId(current_user.id)},
            sort=[('order', -1)]
        )
        max_order = (last.get('order', 0) if last else 0) + 1

        todo = {
            'title': title,
            'desc': desc,
            'date_created': datetime.now(timezone.utc),
            'reminder_time': reminder_time,
            'due_date': due_date,
            'priority': priority,
            'category': category,
            'completed': False,
            'order': max_order,
            'user_id': ObjectId(current_user.id)
        }

        mongo.db.todos.insert_one(todo)
        flash('Task added successfully!', 'success')
        return redirect(url_for('index'))

    # ── Query parameters for search, filter, sort ──
    search = request.args.get('search', '').strip()
    filter_status = request.args.get('status', 'all')
    filter_priority = request.args.get('priority', 'all')
    filter_category = request.args.get('category', 'all')
    sort_by = request.args.get('sort', 'order')

    query = {'user_id': ObjectId(current_user.id)}

    # Exclude manually dismissed tasks
    query['dismissed'] = {'$ne': True}

    and_conditions = []

    # Auto-hide tasks completed more than 1 hour ago (unless user is filtering for completed)
    if filter_status != 'completed':
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        and_conditions.append({
            '$or': [
                {'completed': {'$ne': True}},
                {'completed_at': {'$exists': False}},
                {'completed_at': None},
                {'completed_at': {'$gt': one_hour_ago}}
            ]
        })

    if search:
        and_conditions.append({
            '$or': [
                {'title': {'$regex': search, '$options': 'i'}},
                {'desc': {'$regex': search, '$options': 'i'}}
            ]
        })

    if filter_status == 'completed':
        query['completed'] = True
    elif filter_status == 'pending':
        query['completed'] = {'$ne': True}

    if filter_priority in PRIORITIES:
        query['priority'] = filter_priority

    if filter_category in CATEGORIES:
        query['category'] = filter_category

    if and_conditions:
        query['$and'] = and_conditions

    # Sort
    sort_map = {
        'order': [('order', 1)],
        'date_desc': [('date_created', -1)],
        'date_asc': [('date_created', 1)],
        'due_date': [('due_date', 1)],
        'priority': [('_priority_order', 1)],
    }
    sort_key = sort_map.get(sort_by, [('order', 1)])

    if sort_by == 'priority':
        allToDo = list(mongo.db.todos.find(query))
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        allToDo.sort(key=lambda t: priority_order.get(t.get('priority', 'medium'), 1))
    else:
        allToDo = list(mongo.db.todos.find(query).sort(sort_key))

    # Stats (exclude dismissed)
    all_user_todos = list(mongo.db.todos.find({
        'user_id': ObjectId(current_user.id),
        'dismissed': {'$ne': True}
    }))
    total = len(all_user_todos)
    completed = sum(1 for t in all_user_todos if t.get('completed'))
    pending = total - completed

    return render_template('index.html',
        allToDo=allToDo,
        total=total,
        completed=completed,
        pending=pending,
        search=search,
        filter_status=filter_status,
        filter_priority=filter_priority,
        filter_category=filter_category,
        sort_by=sort_by
    )

# --- Toggle Complete --- #
@app.route('/toggle/<todo_id>')
@login_required
def toggle_complete(todo_id):
    todo = mongo.db.todos.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if todo:
        new_status = not todo.get('completed', False)
        mongo.db.todos.update_one(
            {'_id': ObjectId(todo_id)},
            {'$set': {'completed': new_status}}
        )
        flash('Task marked as ' + ('completed' if new_status else 'pending') + '.', 'success')
    return redirect(url_for('index'))

# --- API: Toggle Complete (AJAX) --- #
@app.route('/api/toggle/<todo_id>', methods=['POST'])
@login_required
def api_toggle_complete(todo_id):
    todo = mongo.db.todos.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if todo:
        new_status = not todo.get('completed', False)
        update_fields = {'completed': new_status}
        if new_status:
            update_fields['completed_at'] = datetime.now(timezone.utc)
        else:
            update_fields['completed_at'] = None
        mongo.db.todos.update_one(
            {'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)},
            {'$set': update_fields}
        )
        # Return updated stats
        all_todos = list(mongo.db.todos.find({
            'user_id': ObjectId(current_user.id),
            'dismissed': {'$ne': True}
        }))
        total = len(all_todos)
        comp = sum(1 for t in all_todos if t.get('completed'))
        return jsonify({
            'status': 'ok', 'completed': new_status,
            'stats': {'total': total, 'completed': comp, 'pending': total - comp}
        })
    return jsonify({'status': 'error'}), 404

# --- API: Delete task (AJAX) --- #
@app.route('/api/delete/<todo_id>', methods=['POST'])
@login_required
def api_delete(todo_id):
    result = mongo.db.todos.delete_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if result.deleted_count:
        all_todos = list(mongo.db.todos.find({
            'user_id': ObjectId(current_user.id),
            'dismissed': {'$ne': True}
        }))
        total = len(all_todos)
        comp = sum(1 for t in all_todos if t.get('completed'))
        return jsonify({
            'status': 'ok',
            'stats': {'total': total, 'completed': comp, 'pending': total - comp}
        })
    return jsonify({'status': 'error'}), 404

# --- API: Reorder tasks (drag & drop) --- #
@app.route('/api/reorder', methods=['POST'])
@login_required
def api_reorder():
    data = request.get_json()
    order_list = data.get('order', [])
    for i, todo_id in enumerate(order_list):
        mongo.db.todos.update_one(
            {'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)},
            {'$set': {'order': i}}
        )
    return jsonify({'status': 'ok'})

# --- API: Add task (AJAX) --- #
@app.route('/api/add', methods=['POST'])
@login_required
def api_add():
    data = request.get_json()
    title = (data.get('title') or '').strip()
    desc = (data.get('desc') or '').strip()
    priority = (data.get('priority') or 'medium').lower()
    category = data.get('category') or 'General'
    due_date_str = (data.get('due_date') or '').strip()
    reminder_str = (data.get('reminder') or '').strip()

    if not title:
        return jsonify({'status': 'error', 'message': 'Title is required.'}), 400
    if not desc:
        return jsonify({'status': 'error', 'message': 'Description is required.'}), 400
    if priority not in PRIORITIES:
        priority = 'medium'
    if category not in CATEGORIES:
        category = 'General'

    reminder_time = None
    if reminder_str:
        local_dt = datetime.fromisoformat(reminder_str)
        local_dt = local_dt.replace(tzinfo=IST)
        reminder_time = local_dt.astimezone(timezone.utc)

    due_date = None
    if due_date_str:
        local_dt = datetime.fromisoformat(due_date_str)
        local_dt = local_dt.replace(tzinfo=IST)
        due_date = local_dt.astimezone(timezone.utc)

    last = mongo.db.todos.find_one(
        {'user_id': ObjectId(current_user.id)},
        sort=[('order', -1)]
    )
    max_order = (last.get('order', 0) if last else 0) + 1

    todo = {
        'title': title,
        'desc': desc,
        'date_created': datetime.now(timezone.utc),
        'reminder_time': reminder_time,
        'due_date': due_date,
        'priority': priority,
        'category': category,
        'completed': False,
        'order': max_order,
        'user_id': ObjectId(current_user.id)
    }

    result = mongo.db.todos.insert_one(todo)
    todo['_id'] = result.inserted_id

    # Build response with rendered card HTML
    now_utc = datetime.now(timezone.utc)
    is_overdue = due_date and due_date < now_utc

    # Stats
    all_todos = list(mongo.db.todos.find({
        'user_id': ObjectId(current_user.id),
        'dismissed': {'$ne': True}
    }))
    total = len(all_todos)
    comp = sum(1 for t in all_todos if t.get('completed'))

    card_data = {
        'id': str(todo['_id']),
        'title': title,
        'desc': desc,
        'priority': priority,
        'category': category,
        'date_created': to_local_filter(todo['date_created']).strftime('%b %d, %Y • %I:%M %p'),
        'due_date': to_local_filter(due_date).strftime('%b %d, %Y • %I:%M %p') if due_date else None,
        'reminder_time': to_local_filter(reminder_time).strftime('%b %d, %Y • %I:%M %p') if reminder_time else None,
        'is_overdue': is_overdue,
        'completed': False
    }

    return jsonify({
        'status': 'ok',
        'task': card_data,
        'stats': {'total': total, 'completed': comp, 'pending': total - comp}
    })

# --- API: Smart parse natural language task input --- #
@app.route('/api/smart-parse', methods=['POST'])
@login_required
def api_smart_parse():
    data = request.get_json()
    text = (data.get('text') or '').strip()
    if not text:
        return jsonify({'title': '', 'due_date_str': '', 'category': '', 'priority': '', 'due_date_iso': ''})

    result = parse_smart_input(text)

    # Validate category against allowed list
    if result['category'] and result['category'] not in CATEGORIES:
        # Try case-insensitive match
        matched = False
        for cat in CATEGORIES:
            if cat.lower() == result['category'].lower():
                result['category'] = cat
                matched = True
                break
        if not matched:
            result['category'] = ''

    # Validate priority
    if result['priority'] and result['priority'] not in PRIORITIES:
        result['priority'] = ''

    return jsonify(result)

# --- API: Fetch filtered tasks (AJAX) --- #
@app.route('/api/tasks')
@login_required
def api_tasks():
    search = request.args.get('search', '').strip()
    filter_status = request.args.get('status', 'all')
    filter_priority = request.args.get('priority', 'all')
    filter_category = request.args.get('category', 'all')
    sort_by = request.args.get('sort', 'order')

    query = {'user_id': ObjectId(current_user.id)}
    query['dismissed'] = {'$ne': True}

    and_conditions = []

    if filter_status != 'completed':
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        and_conditions.append({
            '$or': [
                {'completed': {'$ne': True}},
                {'completed_at': {'$exists': False}},
                {'completed_at': None},
                {'completed_at': {'$gt': one_hour_ago}}
            ]
        })

    if search:
        and_conditions.append({
            '$or': [
                {'title': {'$regex': search, '$options': 'i'}},
                {'desc': {'$regex': search, '$options': 'i'}}
            ]
        })

    if filter_status == 'completed':
        query['completed'] = True
    elif filter_status == 'pending':
        query['completed'] = {'$ne': True}

    if filter_priority in PRIORITIES:
        query['priority'] = filter_priority
    if filter_category in CATEGORIES:
        query['category'] = filter_category

    if and_conditions:
        query['$and'] = and_conditions

    sort_map = {
        'order': [('order', 1)],
        'date_desc': [('date_created', -1)],
        'date_asc': [('date_created', 1)],
        'due_date': [('due_date', 1)],
    }

    now_utc = datetime.now(timezone.utc)

    if sort_by == 'priority':
        todos = list(mongo.db.todos.find(query))
        priority_order = {'high': 0, 'medium': 1, 'low': 2}
        todos.sort(key=lambda t: priority_order.get(t.get('priority', 'medium'), 1))
    else:
        sort_key = sort_map.get(sort_by, [('order', 1)])
        todos = list(mongo.db.todos.find(query).sort(sort_key))

    tasks = []
    for t in todos:
        t_due = ensure_aware(t.get('due_date'))
        is_overdue = bool(t_due and t_due < now_utc and not t.get('completed', False))
        tasks.append({
            'id': str(t['_id']),
            'title': t['title'],
            'desc': t.get('desc', ''),
            'priority': t.get('priority', 'medium'),
            'category': t.get('category', 'General'),
            'date_created': to_local_filter(t['date_created']).strftime('%b %d, %Y • %I:%M %p'),
            'due_date': to_local_filter(t['due_date']).strftime('%b %d, %Y • %I:%M %p') if t.get('due_date') else None,
            'reminder_time': to_local_filter(t['reminder_time']).strftime('%b %d, %Y • %I:%M %p') if t.get('reminder_time') else None,
            'is_overdue': is_overdue,
            'completed': t.get('completed', False)
        })

    all_todos = list(mongo.db.todos.find({
        'user_id': ObjectId(current_user.id),
        'dismissed': {'$ne': True}
    }))
    total = len(all_todos)
    comp = sum(1 for t in all_todos if t.get('completed'))

    return jsonify({
        'tasks': tasks,
        'stats': {'total': total, 'completed': comp, 'pending': total - comp}
    })

# --- API: Update task (AJAX) --- #
@app.route('/api/update/<todo_id>', methods=['POST'])
@login_required
def api_update(todo_id):
    todo = mongo.db.todos.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if not todo:
        return jsonify({'status': 'error', 'message': 'Task not found.'}), 404

    data = request.get_json()
    title = (data.get('title') or '').strip()
    desc = (data.get('desc') or '').strip()
    priority = (data.get('priority') or 'medium').lower()
    category = data.get('category') or 'General'
    due_date_str = (data.get('due_date') or '').strip()
    reminder_str = (data.get('reminder') or '').strip()

    if not title:
        return jsonify({'status': 'error', 'message': 'Title is required.'}), 400

    if priority not in PRIORITIES:
        priority = 'medium'
    if category not in CATEGORIES:
        category = 'General'

    reminder_time = None
    if reminder_str:
        local_dt = datetime.fromisoformat(reminder_str)
        local_dt = local_dt.replace(tzinfo=IST)
        reminder_time = local_dt.astimezone(timezone.utc)

    due_date = None
    if due_date_str:
        local_dt = datetime.fromisoformat(due_date_str)
        local_dt = local_dt.replace(tzinfo=IST)
        due_date = local_dt.astimezone(timezone.utc)

    mongo.db.todos.update_one(
        {'_id': ObjectId(todo_id)},
        {'$set': {
            'title': title,
            'desc': desc,
            'reminder_time': reminder_time,
            'due_date': due_date,
            'priority': priority,
            'category': category,
            'reminder_dismissed': False
        }}
    )

    now_utc = datetime.now(timezone.utc)
    is_overdue = bool(due_date and due_date < now_utc and not todo.get('completed', False))

    card_data = {
        'id': str(todo['_id']),
        'title': title,
        'desc': desc,
        'priority': priority,
        'category': category,
        'date_created': to_local_filter(todo['date_created']).strftime('%b %d, %Y • %I:%M %p'),
        'due_date': to_local_filter(due_date).strftime('%b %d, %Y • %I:%M %p') if due_date else None,
        'reminder_time': to_local_filter(reminder_time).strftime('%b %d, %Y • %I:%M %p') if reminder_time else None,
        'is_overdue': is_overdue,
        'completed': todo.get('completed', False)
    }

    return jsonify({'status': 'ok', 'task': card_data})

# --- API: Get single task data for edit modal --- #
@app.route('/api/task/<todo_id>')
@login_required
def api_get_task(todo_id):
    todo = mongo.db.todos.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if not todo:
        return jsonify({'status': 'error'}), 404

    # Convert datetimes to local ISO format for datetime-local inputs
    def to_input_format(dt):
        if not dt:
            return ''
        local = to_local_filter(dt)
        if hasattr(local, 'strftime'):
            return local.strftime('%Y-%m-%dT%H:%M')
        return ''

    return jsonify({
        'status': 'ok',
        'task': {
            'id': str(todo['_id']),
            'title': todo['title'],
            'desc': todo.get('desc', ''),
            'priority': todo.get('priority', 'medium'),
            'category': todo.get('category', 'General'),
            'due_date': to_input_format(todo.get('due_date')),
            'reminder': to_input_format(todo.get('reminder_time'))
        }
    })

# --- API: Dismiss completed task (remove from view) --- #
@app.route('/api/dismiss-task/<todo_id>', methods=['POST'])
@login_required
def dismiss_task(todo_id):
    mongo.db.todos.update_one(
        {'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)},
        {'$set': {'dismissed': True}}
    )
    all_todos = list(mongo.db.todos.find({
        'user_id': ObjectId(current_user.id),
        'dismissed': {'$ne': True}
    }))
    total = len(all_todos)
    comp = sum(1 for t in all_todos if t.get('completed'))
    return jsonify({
        'status': 'ok',
        'stats': {'total': total, 'completed': comp, 'pending': total - comp}
    })

# --- Update --- #
@app.route('/update/<todo_id>', methods=['GET', 'POST'])
@login_required
def update(todo_id):
    todo = mongo.db.todos.find_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if not todo:
        flash("Task not found or unauthorized.", "danger")
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        desc = request.form.get('desc', '').strip()
        reminder = request.form.get('reminder', '').strip()
        priority = request.form.get('priority', 'medium').lower()
        category = request.form.get('category', 'General')
        due_date_str = request.form.get('due_date', '').strip()

        if not title:
            flash('Title is required.', 'danger')
            return redirect(url_for('update', todo_id=todo_id))

        if priority not in PRIORITIES:
            priority = 'medium'
        if category not in CATEGORIES:
            category = 'General'

        reminder_time = None
        if reminder:
            local_dt = datetime.fromisoformat(reminder)
            local_dt = local_dt.replace(tzinfo=IST)
            reminder_time = local_dt.astimezone(timezone.utc)

        due_date = None
        if due_date_str:
            local_dt = datetime.fromisoformat(due_date_str)
            local_dt = local_dt.replace(tzinfo=IST)
            due_date = local_dt.astimezone(timezone.utc)

        mongo.db.todos.update_one(
            {'_id': ObjectId(todo_id)},
            {'$set': {
                'title': title,
                'desc': desc,
                'reminder_time': reminder_time,
                'due_date': due_date,
                'priority': priority,
                'category': category,
                'reminder_dismissed': False
            }}
        )

        flash('Task updated successfully!', 'success')
        return redirect(url_for('index'))

    return render_template('update.html', todo=todo)

@app.route('/delete/<todo_id>')
@login_required
def delete(todo_id):
    result = mongo.db.todos.delete_one({'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)})
    if result.deleted_count:
        flash('Task deleted successfully.', 'success')
    else:
        flash('Task not found or unauthorized.', 'danger')
    return redirect(url_for('index'))

@app.route('/about')
@login_required
def about():
    return render_template('about.html')

@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        query = request.form.get('query', '').strip()

        errors = []
        if not name or len(name) < 2:
            errors.append('Name must be at least 2 characters.')
        if len(name) > 100:
            errors.append('Name must be under 100 characters.')
        if not email:
            errors.append('Email is required.')
        elif not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            errors.append('Please enter a valid email address.')
        if phone and not re.match(r'^[\d\s\+\-\(\)]{7,20}$', phone):
            errors.append('Please enter a valid phone number.')
        if not query or len(query) < 10:
            errors.append('Message must be at least 10 characters.')
        if len(query) > 2000:
            errors.append('Message must be under 2000 characters.')

        if errors:
            for err in errors:
                flash(err, 'danger')
            return redirect('/contact')

        if not phone:
            phone = 'Not provided'

        try:
            mongo.db.contacts.insert_one({
                'name': name, 'phone': phone, 'email': email,
                'query': query, 'submitted_at': datetime.now(timezone.utc)
            })
        except Exception as e:
            print(f"❌ DB error: {e}")

        recipient = os.getenv('MAIL_RECIPIENT')
        if not recipient:
            flash('Message saved. Email config error.', 'warning')
            return redirect('/contact')

        try:
            msg = MailMessage(
                subject=f"[Daily Flow] New Contact from {name}",
                sender=app.config['MAIL_USERNAME'],
                recipients=[recipient],
                reply_to=email
            )
            msg.body = f"From: {name}\nEmail: {email}\nPhone: {phone}\nMessage:\n{query}"
            msg.html = f"""\
<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f0f2f5;padding:32px 16px;"><tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 8px rgba(0,0,0,0.05);">
<tr><td style="background:#fff;padding:28px 32px 20px;text-align:center;border-bottom:1px solid #edf0f4;">
<div style="font-size:28px;margin-bottom:6px;">✉️</div>
<h1 style="margin:0;color:#2d3748;font-size:19px;font-weight:700;">New Contact Submission</h1>
<p style="margin:6px 0 0;color:#a0aec0;font-size:12.5px;">Received via Daily Flow</p></td></tr>
<tr><td style="padding:24px 32px 0;"><p style="margin:0 0 12px;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;font-weight:600;">Sender Details</p>
<table width="100%"><tr><td style="padding:7px 0;border-bottom:1px solid #eef1f5;width:80px;font-size:12px;color:#a0aec0;font-weight:500;">Name</td>
<td style="padding:7px 0;border-bottom:1px solid #eef1f5;font-size:13.5px;color:#2d3748;font-weight:600;">{name}</td></tr>
<tr><td style="padding:7px 0;border-bottom:1px solid #eef1f5;font-size:12px;color:#a0aec0;font-weight:500;">Email</td>
<td style="padding:7px 0;border-bottom:1px solid #eef1f5;"><a href="mailto:{email}" style="font-size:13.5px;color:#5b6abf;text-decoration:none;">{email}</a></td></tr>
<tr><td style="padding:7px 0;font-size:12px;color:#a0aec0;font-weight:500;">Phone</td>
<td style="padding:7px 0;font-size:13.5px;color:#2d3748;">{phone}</td></tr></table></td></tr>
<tr><td style="padding:20px 32px 0;"><p style="margin:0 0 10px;font-size:11px;text-transform:uppercase;letter-spacing:0.8px;color:#a0aec0;font-weight:600;">Message</p>
<div style="background:#f8f9fb;border-left:3px solid #cbd5e0;border-radius:0 8px 8px 0;padding:14px 18px;">
<p style="margin:0;font-size:13.5px;color:#4a5568;line-height:1.7;white-space:pre-wrap;">{query}</p></div></td></tr>
<tr><td style="padding:22px 32px 0;" align="center"><a href="mailto:{email}?subject=Re: Your message on Daily Flow"
style="display:inline-block;background:#5b6abf;color:#fff;text-decoration:none;padding:9px 26px;border-radius:6px;font-size:12.5px;font-weight:600;">Reply to {name}</a></td></tr>
<tr><td style="padding:20px 32px 24px;"><p style="margin:0;font-size:11.5px;color:#c0c8d4;text-align:center;">
Submitted on {datetime.now(IST).strftime('%B %d, %Y at %I:%M %p IST')}</p></td></tr>
<tr><td style="background:#f8f9fb;padding:14px 32px;border-top:1px solid #edf0f4;text-align:center;">
<p style="margin:0;font-size:11px;color:#b8c2cc;text-align:center;">Daily Flow &nbsp;·&nbsp; <a href="https://github.com/Athrv16" style="color:#7c8acf;text-decoration:none;">GitHub</a></p></td></tr>
</table></td></tr></table></body></html>"""
            with mail.connect() as conn:
                conn.send(msg)
            flash('Your message has been sent successfully!', 'success')
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash('Message saved but email failed to send.', 'warning')

        return redirect('/contact')

    return render_template('contact.html')

# ── Reminder APIs ──
@app.route('/api/check-reminders')
@login_required
def check_reminders():
    now_utc = datetime.now(timezone.utc)
    todos = mongo.db.todos.find({
        'user_id': ObjectId(current_user.id),
        'reminder_time': {'$ne': None, '$lte': now_utc},
        'reminder_dismissed': {'$ne': True}
    })
    result = []
    for todo in todos:
        result.append({
            'id': str(todo['_id']),
            'title': todo['title'],
            'desc': todo['desc'],
            'reminder_time': to_local_filter(todo['reminder_time']).strftime('%b %d, %Y • %I:%M %p')
        })
    return jsonify(result)

@app.route('/api/dismiss-reminder/<todo_id>', methods=['POST'])
@login_required
def dismiss_reminder(todo_id):
    mongo.db.todos.update_one(
        {'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)},
        {'$set': {'reminder_dismissed': True}}
    )
    return jsonify({'status': 'ok'})

@app.route('/api/snooze-reminder/<todo_id>', methods=['POST'])
@login_required
def snooze_reminder(todo_id):
    new_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    mongo.db.todos.update_one(
        {'_id': ObjectId(todo_id), 'user_id': ObjectId(current_user.id)},
        {'$set': {'reminder_time': new_time, 'reminder_dismissed': False}}
    )
    return jsonify({'status': 'snoozed', 'new_time': to_local_filter(new_time).strftime('%I:%M %p')})

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=True)
